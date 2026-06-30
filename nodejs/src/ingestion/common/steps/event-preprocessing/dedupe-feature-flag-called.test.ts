import { isDropResult, isOkResult } from '~/ingestion/framework/results'
import {
    FeatureFlagCalledDedupMode,
    FeatureFlagCalledDedupService,
    featureFlagCalledDedupKey,
} from '~/ingestion/utils/feature-flag-called-dedup/feature-flag-called-dedup-service'
import { getMetricValues, resetMetrics } from '~/tests/helpers/metrics'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'

import { DedupeFeatureFlagCalledStepInput, createDedupeFeatureFlagCalledStep } from './dedupe-feature-flag-called'

const createMockService = (
    mode: FeatureFlagCalledDedupMode = 'drop',
    enabledForTeam = true
): jest.Mocked<FeatureFlagCalledDedupService> => ({
    mode,
    isEnabledForTeam: jest.fn().mockReturnValue(enabledForTeam),
    claimKeys: jest.fn(),
})

// Callers pass an explicit `undefined` for `properties` to reach `overrides`;
// a defaulted parameter accepts `undefined` (and applies the default) even
// under strict mode.
const createInput = (
    properties: Record<string, unknown> = { $feature_flag: 'my-flag', $feature_flag_response: true },
    overrides: { event?: string; distinctId?: string; teamId?: number; uuid?: string } = {}
): DedupeFeatureFlagCalledStepInput => ({
    event: createTestPluginEvent({
        event: overrides.event ?? '$feature_flag_called',
        distinct_id: overrides.distinctId ?? 'user-1',
        uuid: overrides.uuid ?? '123e4567-e89b-12d3-a456-426614174000',
        properties,
    }),
    team: createTestTeam({ id: overrides.teamId ?? 1 }),
})

describe('createDedupeFeatureFlagCalledStep', () => {
    beforeEach(() => {
        resetMetrics()
    })

    it('passes everything through when no service is provided', async () => {
        const step = createDedupeFeatureFlagCalledStep(undefined)

        const results = await step([createInput(), createInput()])

        expect(results).toHaveLength(2)
        results.forEach((result) => expect(isOkResult(result)).toBe(true))
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

    it('ignores events without a uuid', async () => {
        const service = createMockService()
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([createInput(undefined, { uuid: '' })])

        expect(isOkResult(results[0])).toBe(true)
        expect(service.claimKeys).not.toHaveBeenCalled()
    })

    it('passes first-seen events and drops in-batch duplicates in drop mode', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        const inputs = [createInput(undefined, { uuid: 'uuid-1' }), createInput(undefined, { uuid: 'uuid-2' })]
        const results = await step(inputs)

        expect(results).toHaveLength(2)
        // Two identical tuples produce the same claim key in one claimKeys
        // call, each tagged with its own event uuid.
        const expectedKey = featureFlagCalledDedupKey(1, 'user-1', 'my-flag', true, undefined, undefined)
        expect(service.claimKeys).toHaveBeenCalledWith([
            { key: expectedKey, claimId: 'uuid-1' },
            { key: expectedKey, claimId: 'uuid-2' },
        ])
        expect(isOkResult(results[0])).toBe(true)
        expect(isDropResult(results[1])).toBe(true)
        if (isDropResult(results[1])) {
            expect(results[1].reason).toBe('feature_flag_called_duplicate')
        }
        expect(await getMetricValues('ingestion_feature_flag_called_dedup_events_total')).toEqual(
            expect.arrayContaining([
                { labels: { outcome: 'first_seen' }, value: 1 },
                { labels: { outcome: 'duplicate_dropped' }, value: 1 },
            ])
        )
    })

    it('passes duplicates through in shadow mode', async () => {
        const service = createMockService('shadow')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([
            createInput(undefined, { uuid: 'uuid-1' }),
            createInput(undefined, { uuid: 'uuid-2' }),
        ])

        expect(results).toHaveLength(2)
        results.forEach((result) => expect(isOkResult(result)).toBe(true))
        expect(service.claimKeys).toHaveBeenCalledTimes(1)
        expect(await getMetricValues('ingestion_feature_flag_called_dedup_events_total')).toEqual(
            expect.arrayContaining([
                { labels: { outcome: 'first_seen' }, value: 1 },
                { labels: { outcome: 'duplicate_shadow' }, value: 1 },
            ])
        )
    })

    it('maps claim results back when the batch interleaves deduped and ignored events', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        const inputs = [
            createInput({}, { event: '$pageview' }),
            createInput(undefined, { uuid: 'uuid-1' }),
            createInput({ $feature_flag_response: true }),
            createInput(undefined, { uuid: 'uuid-2' }),
        ]
        const results = await step(inputs)

        expect(results).toHaveLength(4)
        expect(isOkResult(results[0])).toBe(true)
        expect(isOkResult(results[1])).toBe(true)
        expect(isOkResult(results[2])).toBe(true)
        expect(isDropResult(results[3])).toBe(true)
        const expectedKey = featureFlagCalledDedupKey(1, 'user-1', 'my-flag', true, undefined, undefined)
        expect(service.claimKeys).toHaveBeenCalledWith([
            { key: expectedKey, claimId: 'uuid-1' },
            { key: expectedKey, claimId: 'uuid-2' },
        ])
    })

    it('fails open when the service returns fewer results than claims', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true])
        const step = createDedupeFeatureFlagCalledStep(service)

        const results = await step([
            createInput(undefined, { uuid: 'uuid-1' }),
            createInput(undefined, { uuid: 'uuid-2' }),
        ])

        expect(results).toHaveLength(2)
        results.forEach((result) => expect(isOkResult(result)).toBe(true))
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

        const claims = service.claimKeys.mock.calls[0][0]
        expect(new Set(claims.map((claim) => claim.key)).size).toBe(4)
    })

    it('builds different claim keys when only $feature_flag_has_experiment differs', async () => {
        // Experiment exposures must not be deduped against otherwise-identical
        // non-experiment calls, so the property has to reach the key.
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, true])
        const step = createDedupeFeatureFlagCalledStep(service)

        await step([
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: true, $feature_flag_has_experiment: true }),
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: true, $feature_flag_has_experiment: false }),
        ])

        const claims = service.claimKeys.mock.calls[0][0]
        expect(claims[0].key).not.toBe(claims[1].key)
    })

    it('builds identical claim keys for identical tuples', async () => {
        const service = createMockService('drop')
        service.claimKeys.mockResolvedValue([true, false])
        const step = createDedupeFeatureFlagCalledStep(service)

        await step([
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: 'variant-1', $groups: { org: 'o1' } }),
            createInput({ $feature_flag: 'flag-a', $feature_flag_response: 'variant-1', $groups: { org: 'o1' } }),
        ])

        const claims = service.claimKeys.mock.calls[0][0]
        expect(claims[0].key).toBe(claims[1].key)
    })
})
