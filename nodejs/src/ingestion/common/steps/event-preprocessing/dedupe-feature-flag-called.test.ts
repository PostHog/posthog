import { createTestPluginEvent } from '../../../tests/helpers/plugin-event'
import { createTestTeam } from '../../../tests/helpers/team'
import { isDropResult, isOkResult } from '../pipelines/results'
import {
    FeatureFlagCalledDedupMode,
    FeatureFlagCalledDedupService,
} from '../utils/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { DedupeFeatureFlagCalledStepInput, createDedupeFeatureFlagCalledStep } from './dedupe-feature-flag-called'

const createMockService = (
    mode: FeatureFlagCalledDedupMode = 'drop',
    enabledForTeam = true
): jest.Mocked<FeatureFlagCalledDedupService> => ({
    mode,
    isEnabledForTeam: jest.fn().mockReturnValue(enabledForTeam),
    claimKeys: jest.fn(),
})

const createInput = (
    properties: Record<string, unknown> = { $feature_flag: 'my-flag', $feature_flag_response: true },
    overrides: { event?: string; distinctId?: string; teamId?: number } = {}
): DedupeFeatureFlagCalledStepInput => ({
    event: createTestPluginEvent({
        event: overrides.event ?? '$feature_flag_called',
        distinct_id: overrides.distinctId ?? 'user-1',
        properties,
    }),
    team: createTestTeam({ id: overrides.teamId ?? 1 }),
})

describe('createDedupeFeatureFlagCalledStep', () => {
    it('passes everything through when no service is provided', async () => {
        const step = createDedupeFeatureFlagCalledStep(undefined)

        const results = await step([createInput(), createInput()])

        expect(results).toHaveLength(2)
        results.forEach((result) => expect(isOkResult(result)).toBe(true))
    })

    it('passes everything through when mode is disabled', async () => {
        const service = createMockService('disabled')
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([createInput()])

        expect(isOkResult(results[0])).toBe(true)
        expect(service.claimKeys).not.toHaveBeenCalled()
    })

    it('handles empty batch', async () => {
        const service = createMockService()
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([])

        expect(results).toHaveLength(0)
        expect(service.claimKeys).not.toHaveBeenCalled()
    })

    it('ignores events that are not $feature_flag_called', async () => {
        const service = createMockService()
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([createInput({}, { event: '$pageview' })])

        expect(isOkResult(results[0])).toBe(true)
        expect(service.claimKeys).not.toHaveBeenCalled()
    })

    it('ignores teams the dedup is not enabled for', async () => {
        const service = createMockService('drop', false)
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([createInput()])

        expect(isOkResult(results[0])).toBe(true)
        expect(service.claimKeys).not.toHaveBeenCalled()
    })

    it('ignores events without a string $feature_flag property', async () => {
        const service = createMockService()
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([
            createInput({ $feature_flag_response: true }),
            createInput({ $feature_flag: 42, $feature_flag_response: true }),
        ])

        expect(results).toHaveLength(2)
        results.forEach((result) => expect(isOkResult(result)).toBe(true))
        expect(service.claimKeys).not.toHaveBeenCalled()
    })

    it('passes first-seen events and drops in-batch duplicates in drop mode', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        const inputs = [createInput(), createInput()]
        const results = await step(inputs)

        expect(results).toHaveLength(2)
        // Two identical inputs produce the same claim key in one claimKeys call
        const keys = service.claimKeys.mock.calls[0][0]
        expect(keys).toHaveLength(2)
        expect(keys[0]).toBe(keys[1])
        expect(isOkResult(results[0])).toBe(true)
        expect(isDropResult(results[1])).toBe(true)
        if (isDropResult(results[1])) {
            expect(results[1].reason).toBe('feature_flag_called_duplicate')
        }
    })

    it('passes duplicates through in shadow mode', async () => {
        const service = createMockService('shadow')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([createInput(), createInput()])

        expect(results).toHaveLength(2)
        results.forEach((result) => expect(isOkResult(result)).toBe(true))
        expect(service.claimKeys).toHaveBeenCalledTimes(1)
    })

    it('maps claim results back when the batch interleaves deduped and ignored events', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        const inputs = [
            createInput({}, { event: '$pageview' }),
            createInput(),
            createInput({ $feature_flag_response: true }),
            createInput(),
        ]
        const results = await step(inputs)

        expect(results).toHaveLength(4)
        expect(isOkResult(results[0])).toBe(true)
        expect(isOkResult(results[1])).toBe(true)
        expect(isOkResult(results[2])).toBe(true)
        expect(isDropResult(results[3])).toBe(true)
        expect(service.claimKeys).toHaveBeenCalledWith([expect.any(String), expect.any(String)])
    })

    it('builds different claim keys for different flag tuples', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, true, true, true])
        const step = createDedupeFeatureFlagCalledStep(service)

        await step([
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: true }),
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: false }),
            createInput({ $feature_flag: 'flag-b', $feature_flag_response: true }),
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: true }, { distinctId: 'user-2' }),
        ])

        const keys = service.claimKeys.mock.calls[0][0]
        expect(new Set(keys).size).toBe(4)
    })

    it('builds identical claim keys for identical tuples', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        await step([
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: 'variant-1', $groups: { org: 'o1' } }),
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: 'variant-1', $groups: { org: 'o1' } }),
        ])

        const keys = service.claimKeys.mock.calls[0][0]
        expect(keys[0]).toBe(keys[1])
    })
})
