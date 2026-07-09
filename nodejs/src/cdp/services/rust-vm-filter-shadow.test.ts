import { init } from '@posthog/hogvm-node'

import { HogBytecode } from '~/cdp/types'

import {
    FilterShadowCapturedInvocation,
    FilterShadowNodeResult,
    FilterShadowOutcome,
    RustVmFilterShadow,
    classifyFilterShadowOutcome,
    filterShadowComparison,
} from './rust-vm-filter-shadow'

jest.mock('@posthog/hogvm-node', () => ({
    init: jest.fn(),
    executeBatch: jest.fn(),
}))

const mockHogvmNode = jest.mocked(jest.requireMock<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node'))

// A trivially-matching filter program; grouping keys off the array reference, so tests that want
// two groups pass two distinct arrays and tests that want one group reuse the same reference.
const MATCH_BYTECODE: HogBytecode = ['_H', 1, 29]

const node = (match: boolean, error?: string): FilterShadowNodeResult => ({ match, error, durationMs: 1 })

const capture = (
    functionId: string,
    globals: Record<string, unknown>,
    nodeResult: FilterShadowNodeResult,
    bytecode: HogBytecode = MATCH_BYTECODE
): FilterShadowCapturedInvocation => ({
    functionId,
    teamId: 1,
    bytecode,
    globalsJson: JSON.stringify(globals),
    node: nodeResult,
})

async function outcomeCounts(): Promise<Record<string, number>> {
    const data = await filterShadowComparison.get()
    return Object.fromEntries(data.values.map((v) => [v.labels.outcome, v.value]))
}

describe('RustVmFilterShadow', () => {
    beforeEach(() => {
        jest.clearAllMocks()
        filterShadowComparison.reset()
    })

    describe('classifyFilterShadowOutcome', () => {
        it.each<
            [
                string,
                FilterShadowNodeResult,
                { result?: unknown; error?: string; durationUs: number } | undefined,
                FilterShadowOutcome,
            ]
        >([
            ['both matched', node(true), { result: true, durationUs: 1 }, 'match'],
            ['both did not match', node(false), { result: false, durationUs: 1 }, 'match'],
            ['node matched, rust did not', node(true), { result: false, durationUs: 1 }, 'result_mismatch'],
            ['node did not match, rust did', node(false), { result: true, durationUs: 1 }, 'result_mismatch'],
            // A non-boolean rust result is a non-match, exactly as the node filtering treats it.
            ['rust returns non-boolean truthy', node(false), { result: 1, durationUs: 1 }, 'match'],
            ['rust non-boolean vs node match', node(true), { result: 1, durationUs: 1 }, 'result_mismatch'],
            ['both errored', node(false, 'boom'), { error: 'Division by zero', durationUs: 1 }, 'match'],
            ['node ok, rust errored', node(true), { error: 'Division by zero', durationUs: 1 }, 'status_mismatch'],
            ['node errored, rust ok', node(false, 'boom'), { result: false, durationUs: 1 }, 'status_mismatch'],
            [
                'unsupported host function',
                node(true),
                { error: 'Native call failed: unsupported_ext_fn:geoipLookup', durationUs: 1 },
                'skipped_unsupported',
            ],
            [
                'host function missing from rust vm',
                node(true),
                { error: 'Unknown Global sendEmail', durationUs: 1 },
                'skipped_unsupported',
            ],
            ['missing rust result', node(true), undefined, 'rust_error'],
        ])('%s', (_name, nodeResult, rust, expected) => {
            expect(classifyFilterShadowOutcome(nodeResult, rust)).toEqual(expected)
        })
    })

    describe('flush', () => {
        let shadow: RustVmFilterShadow

        beforeEach(() => {
            shadow = new RustVmFilterShadow({ sampleRate: 1, mmdbPath: '/dev/null' })
        })

        it('groups captures by bytecode reference across functions, pairing rust results by index', async () => {
            const filterA: HogBytecode = ['_H', 1, 29]
            const filterB: HogBytecode = ['_H', 1, 30]
            // Two different functions share filterA -> one batch; fn-b also has a distinct mapping
            // filter (filterB) -> a separate batch.
            shadow.capture(capture('fn-a', { uuid: 'a1' }, node(true), filterA))
            shadow.capture(capture('fn-b', { uuid: 'b1' }, node(true), filterA))
            shadow.capture(capture('fn-b', { uuid: 'b2' }, node(false), filterB))

            // Rust returns true for every event; filterA's node(true) captures agree, filterB's
            // node(false) capture diverges.
            mockHogvmNode.executeBatch.mockImplementation((_program, events) =>
                Promise.resolve((events as unknown[]).map(() => ({ result: true, durationUs: 5 })))
            )

            await shadow.flush()

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(2)
            expect(mockHogvmNode.executeBatch.mock.calls[0][0]).toBe(filterA)
            expect(mockHogvmNode.executeBatch.mock.calls[0][1]).toEqual([{ uuid: 'a1' }, { uuid: 'b1' }])
            expect(mockHogvmNode.executeBatch.mock.calls[1][0]).toBe(filterB)
            expect(mockHogvmNode.executeBatch.mock.calls[1][1]).toEqual([{ uuid: 'b2' }])
            // filterA: node(true) vs rust true twice = 2 matches. filterB: node(false) vs rust true = mismatch.
            expect(await outcomeCounts()).toEqual({ match: 2, result_mismatch: 1 })
        })

        it('a failing rust batch resolves the flush, counts rust_error, and does not affect other groups', async () => {
            const filterA: HogBytecode = ['_H', 1, 29]
            const filterB: HogBytecode = ['_H', 1, 30]
            shadow.capture(capture('fn-a', { uuid: 'a1' }, node(true), filterA))
            shadow.capture(capture('fn-b', { uuid: 'b1' }, node(true), filterB))

            mockHogvmNode.executeBatch
                .mockRejectedValueOnce(new Error('napi exploded'))
                .mockResolvedValueOnce([{ result: true, durationUs: 5 }])

            await expect(shadow.flush()).resolves.toBeUndefined()
            expect(await outcomeCounts()).toEqual({ rust_error: 1, match: 1 })
        })

        it('a flush while a native batch is still running drops its captures instead of stacking', async () => {
            let resolveBatch: (results: unknown[]) => void = () => {}
            mockHogvmNode.executeBatch.mockImplementationOnce(
                () => new Promise((resolve) => (resolveBatch = resolve as (results: unknown[]) => void))
            )

            shadow.capture(capture('fn-a', { uuid: 'a1' }, node(true)))
            const firstFlush = shadow.flush()

            shadow.capture(capture('fn-a', { uuid: 'a2' }, node(true)))
            await shadow.flush()

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
            expect(await outcomeCounts()).toEqual({ dropped: 1 })

            resolveBatch([{ result: true, durationUs: 5 }])
            await firstFlush
            expect(await outcomeCounts()).toEqual({ dropped: 1, match: 1 })
        })

        it('filters calling nondeterministic stl fns are skipped at capture, not compared', async () => {
            // CALL_GLOBAL now() — relative-date filters legitimately differ between executions.
            shadow.capture(capture('fn-date', { uuid: 'a' }, node(true), ['_H', 1, 2, 'now', 0, 38]))
            // A string literal that merely contains a fn name (preceded by STRING op 32) must not skip.
            shadow.capture(capture('fn-str', { uuid: 'b' }, node(true), ['_H', 1, 32, 'now', 29]))

            mockHogvmNode.executeBatch.mockResolvedValue([{ result: true, durationUs: 5 }])
            await shadow.flush()

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
            expect(await outcomeCounts()).toEqual({ skipped_nondeterministic: 1, match: 1 })
        })

        it('captures beyond the buffer cap are counted as dropped, not as rust errors', async () => {
            for (let i = 0; i < 10_001; i++) {
                shadow.capture(capture('fn-a', { uuid: 'a' }, node(true)))
            }
            expect(await outcomeCounts()).toEqual({ dropped: 1 })
        })

        it('flush drains the buffer, so a second flush does nothing', async () => {
            shadow.capture(capture('fn-a', { uuid: 'a1' }, node(true)))
            mockHogvmNode.executeBatch.mockResolvedValue([{ result: true, durationUs: 5 }])

            await shadow.flush()
            await shadow.flush()

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
        })
    })

    it('a zero sample rate never captures nor loads the native module', () => {
        const shadow = new RustVmFilterShadow({ sampleRate: 0, mmdbPath: '/dev/null' })
        expect(shadow.shouldCapture()).toEqual(false)
        expect(init).not.toHaveBeenCalled()
    })
})
