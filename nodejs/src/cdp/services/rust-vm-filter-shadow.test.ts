import { HogBytecode } from '~/cdp/types'

import {
    FilterShadowOutcome,
    RustVmFilterShadow,
    classifyFilterShadowOutcome,
    filterShadowComparison,
} from './rust-vm-filter-shadow'

jest.mock('@posthog/hogvm-node', () => ({
    executeBatch: jest.fn(),
}))

const mockHogvmNode = jest.mocked(jest.requireMock<typeof import('@posthog/hogvm-node')>('@posthog/hogvm-node'))

const BYTECODE: HogBytecode = ['_H', 1, 29]

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
            [string, boolean, { result?: unknown; error?: string; durationUs: number } | undefined, FilterShadowOutcome]
        >([
            ['both matched', true, { result: true, durationUs: 1 }, 'match'],
            ['both did not match', false, { result: false, durationUs: 1 }, 'match'],
            ['node matched, rust did not', true, { result: false, durationUs: 1 }, 'mismatch'],
            ['node did not match, rust did', false, { result: true, durationUs: 1 }, 'mismatch'],
            // A non-boolean rust result is treated as a non-match, exactly as Node filtering treats it.
            ['rust non-boolean vs node no-match', false, { result: 1, durationUs: 1 }, 'match'],
            ['rust non-boolean vs node match', true, { result: 1, durationUs: 1 }, 'mismatch'],
            ['rust errored', true, { error: 'Division by zero', durationUs: 1 }, 'error'],
            ['missing rust result', true, undefined, 'error'],
        ])('%s', (_name, nodeMatch, rust, expected) => {
            expect(classifyFilterShadowOutcome(nodeMatch, rust)).toEqual(expected)
        })
    })

    describe('compare', () => {
        let shadow: RustVmFilterShadow

        beforeEach(() => {
            shadow = new RustVmFilterShadow({ sampleRate: 1 })
        })

        it('runs the same bytecode + globals on the rust vm and records a match', async () => {
            mockHogvmNode.executeBatch.mockResolvedValue([{ result: true, durationUs: 5 }])

            await shadow.compare(BYTECODE, { uuid: 'e1' }, true, 2)

            expect(mockHogvmNode.executeBatch).toHaveBeenCalledTimes(1)
            expect(mockHogvmNode.executeBatch.mock.calls[0][0]).toBe(BYTECODE)
            expect(mockHogvmNode.executeBatch.mock.calls[0][1]).toEqual([{ uuid: 'e1' }])
            expect(await outcomeCounts()).toEqual({ match: 1 })
        })

        it('counts a divergent boolean as a mismatch', async () => {
            mockHogvmNode.executeBatch.mockResolvedValue([{ result: false, durationUs: 5 }])

            await shadow.compare(BYTECODE, { uuid: 'e1' }, true, 2)

            expect(await outcomeCounts()).toEqual({ mismatch: 1 })
        })

        it('counts a rust execution error as error, not a mismatch', async () => {
            mockHogvmNode.executeBatch.mockResolvedValue([{ error: 'Division by zero', durationUs: 5 }])

            await shadow.compare(BYTECODE, { uuid: 'e1' }, true, 2)

            expect(await outcomeCounts()).toEqual({ error: 1 })
        })

        it('swallows a rejected native call as error instead of throwing', async () => {
            mockHogvmNode.executeBatch.mockRejectedValue(new Error('napi exploded'))

            await expect(shadow.compare(BYTECODE, { uuid: 'e1' }, true, 2)).resolves.toBeUndefined()
            expect(await outcomeCounts()).toEqual({ error: 1 })
        })

        it('does nothing and never loads the native module when sampling is disabled', async () => {
            const disabled = new RustVmFilterShadow({ sampleRate: 0 })

            await disabled.compare(BYTECODE, { uuid: 'e1' }, true, 2)

            expect(mockHogvmNode.executeBatch).not.toHaveBeenCalled()
            expect(await outcomeCounts()).toEqual({})
        })
    })
})
