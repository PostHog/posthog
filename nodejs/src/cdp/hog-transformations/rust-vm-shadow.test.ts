import { init } from '@posthog/hogvm-node'

import {
    RustVmShadow,
    ShadowNodeResult,
    ShadowOutcome,
    classifyShadowOutcome,
    shadowComparison,
} from './rust-vm-shadow'

jest.mock('@posthog/hogvm-node', () => ({
    init: jest.fn(),
    executeBatch: jest.fn(),
}))

const mockHogvmNode = jest.mocked(jest.requireMock<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node'))

const finishedNode = (execResult: unknown): ShadowNodeResult => ({
    finished: true,
    execResultJson: execResult !== undefined ? JSON.stringify(execResult) : null,
    durationMs: 1,
})

const capture = (functionId: string, globals: Record<string, unknown>, execResult: unknown) => ({
    functionId,
    teamId: 1,
    bytecode: ['_H', 1, 38],
    globalsJson: JSON.stringify(globals),
    node: finishedNode(execResult),
})

async function outcomeCounts(): Promise<Record<string, number>> {
    const data = await shadowComparison.get()
    return Object.fromEntries(data.values.map((v) => [v.labels.outcome, v.value]))
}

describe('RustVmShadow', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        shadowComparison.reset()
    })

    describe('classifyShadowOutcome', () => {
        it.each<
            [
                string,
                ShadowNodeResult,
                { result?: unknown; error?: string; durationUs: number } | undefined,
                ShadowOutcome,
            ]
        >([
            [
                'equal results',
                finishedNode({ a: [1, { b: 2 }] }),
                { result: { a: [1, { b: 2 }] }, durationUs: 1 },
                'match',
            ],
            ['differing results', finishedNode({ a: 1 }), { result: { a: 2 }, durationUs: 1 }, 'result_mismatch'],
            ['node null result vs rust null', finishedNode(undefined), { result: null, durationUs: 1 }, 'match'],
            [
                'node finished but rust errored',
                finishedNode({}),
                { error: 'Division by zero', durationUs: 1 },
                'status_mismatch',
            ],
            [
                'both errored',
                { finished: false, error: 'boom', execResultJson: null, durationMs: 1 },
                { error: 'Division by zero', durationUs: 1 },
                'match',
            ],
            [
                'node errored but rust finished',
                { finished: false, error: 'boom', execResultJson: null, durationMs: 1 },
                { result: 1, durationUs: 1 },
                'status_mismatch',
            ],
            [
                'unsupported host function',
                finishedNode({}),
                { error: 'Native call failed: unsupported_ext_fn:geoipLookup', durationUs: 1 },
                'skipped_unsupported',
            ],
            [
                'host function missing from the rust vm',
                finishedNode({}),
                { error: 'Unknown Global sendEmail', durationUs: 1 },
                'skipped_unsupported',
            ],
            ['missing rust result', finishedNode({}), undefined, 'rust_error'],
        ])('%s', (_name, node, rust, expected) => {
            expect(classifyShadowOutcome(node, rust)).toEqual(expected)
        })
    })

    describe('flush', () => {
        let shadow: RustVmShadow

        beforeEach(() => {
            shadow = new RustVmShadow({ sampleRate: 1, mmdbPath: '/dev/null' })
        })

        it('executes one rust batch per function with the captured pre-execution globals, pairing results by index', async () => {
            shadow.capture(capture('fn-a', { name: 'a1' }, 'ok-a1'))
            shadow.capture(capture('fn-b', { name: 'b1' }, 'ok-b1'))
            shadow.capture(capture('fn-a', { name: 'a2' }, 'ok-a2'))

            mockHogvmNode.executeBatch.mockImplementation((_program, events) =>
                Promise.resolve(
                    (events as { name: string }[]).map((event) => ({
                        // fn-a's second invocation diverges, everything else matches
                        result: event.name === 'a2' ? 'rust-divergence' : `ok-${event.name}`,
                        durationUs: 5,
                    }))
                )
            )

            await shadow.flush()

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(2)
            expect(mockHogvmNode.executeBatch.mock.calls[0][1]).toEqual([{ name: 'a1' }, { name: 'a2' }])
            expect(mockHogvmNode.executeBatch.mock.calls[1][1]).toEqual([{ name: 'b1' }])
            expect(await outcomeCounts()).toEqual({ match: 2, result_mismatch: 1 })
        })

        it('a failing rust batch resolves the flush, counts rust_error, and does not affect other groups', async () => {
            shadow.capture(capture('fn-a', { name: 'a1' }, 'ok-a1'))
            shadow.capture(capture('fn-b', { name: 'b1' }, 'ok-b1'))

            mockHogvmNode.executeBatch
                .mockRejectedValueOnce(new Error('napi exploded'))
                .mockResolvedValueOnce([{ result: 'ok-b1', durationUs: 5 }])

            await expect(shadow.flush()).resolves.toBeUndefined()
            expect(await outcomeCounts()).toEqual({ rust_error: 1, match: 1 })
        })

        it('mutating the node result object after capture does not affect the comparison', async () => {
            // The transformer appends bookkeeping properties to the live execResult object right
            // after execution; the capture must compare against a point-in-time snapshot.
            const execResult: Record<string, unknown> = { properties: { $ip: '1.2.3.0' } }
            shadow.capture(capture('fn-a', { name: 'a1' }, execResult))
            ;(execResult.properties as Record<string, unknown>).$transformations_succeeded = ['fn-a']

            mockHogvmNode.executeBatch.mockResolvedValue([
                { result: { properties: { $ip: '1.2.3.0' } }, durationUs: 5 },
            ])

            await shadow.flush()
            expect(await outcomeCounts()).toEqual({ match: 1 })
        })

        it('captures beyond the buffer cap are counted as dropped, not as rust errors', async () => {
            for (let i = 0; i < 10_001; i++) {
                shadow.capture(capture('fn-a', { name: 'a' }, 'ok'))
            }
            expect(await outcomeCounts()).toEqual({ dropped: 1 })
        })

        it('flush drains the buffer, so a second flush does nothing', async () => {
            shadow.capture(capture('fn-a', { name: 'a1' }, 'ok-a1'))
            mockHogvmNode.executeBatch.mockResolvedValue([{ result: 'ok-a1', durationUs: 5 }])

            await shadow.flush()
            await shadow.flush()

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
        })
    })

    it('a zero sample rate never captures nor loads the native module', () => {
        const shadow = new RustVmShadow({ sampleRate: 0, mmdbPath: '/dev/null' })
        expect(shadow.shouldCapture()).toEqual(false)
        expect(init).not.toHaveBeenCalled()
    })
})
