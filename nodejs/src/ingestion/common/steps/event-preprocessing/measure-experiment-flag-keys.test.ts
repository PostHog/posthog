import { ExperimentFlagKeysManager } from '~/ingestion/common/flag-evaluations/experiment-flag-keys-manager'
import { isOkResult } from '~/ingestion/framework/results'
import { getMetricValues, resetMetrics } from '~/tests/helpers/metrics'
import { createTestPluginEvent } from '~/tests/helpers/plugin-event'
import { createTestTeam } from '~/tests/helpers/team'

import { MeasureExperimentFlagKeysStepInput, createMeasureExperimentFlagKeysStep } from './measure-experiment-flag-keys'

const createMockManager = (
    getExperimentFlagKeys: jest.Mock = jest.fn().mockResolvedValue({})
): jest.Mocked<ExperimentFlagKeysManager> =>
    ({ getExperimentFlagKeys }) as unknown as jest.Mocked<ExperimentFlagKeysManager>

const createInput = (
    event: string,
    teamId: number,
    properties: Record<string, unknown> = { $feature_flag: 'my-flag' }
): MeasureExperimentFlagKeysStepInput => ({
    event: createTestPluginEvent({ event, distinct_id: 'user-1', properties }),
    team: createTestTeam({ id: teamId }),
})

// Lets the fire-and-forget lookups and their rejection handler settle.
const flushMicrotasks = (): Promise<void> => new Promise((resolve): void => void setImmediate(resolve))

describe('createMeasureExperimentFlagKeysStep', () => {
    beforeEach(() => {
        resetMetrics()
    })

    it('loads every team in the chunk in one batch', async () => {
        const getExperimentFlagKeys = jest.fn().mockResolvedValue({})
        const step = createMeasureExperimentFlagKeysStep(createMockManager(getExperimentFlagKeys))

        await step([
            createInput('$feature_flag_called', 1),
            createInput('$feature_flag_called', 1, { $feature_flag: 'other-flag' }),
            createInput('$feature_flag_called', 2),
            createInput('$pageview', 3),
        ])
        await flushMicrotasks()

        expect(getExperimentFlagKeys).toHaveBeenCalledTimes(1)
        expect(getExperimentFlagKeys).toHaveBeenCalledWith([1, 2])
    })

    it('counts every event, not every distinct flag, so the split tracks traffic', async () => {
        const getExperimentFlagKeys = jest.fn().mockResolvedValue({ '1': new Set(['experiment-flag']) })
        const step = createMeasureExperimentFlagKeysStep(createMockManager(getExperimentFlagKeys))

        await step([
            createInput('$feature_flag_called', 1, { $feature_flag: 'experiment-flag' }),
            createInput('$feature_flag_called', 1, { $feature_flag: 'experiment-flag' }),
            createInput('$feature_flag_called', 1, { $feature_flag: 'experiment-flag' }),
            createInput('$feature_flag_called', 1, { $feature_flag: 'plain-flag' }),
        ])
        await flushMicrotasks()

        expect(await getMetricValues('ingestion_experiment_flag_keys_lookup_total')).toEqual([
            { labels: { result: 'has_experiment' }, value: 3 },
            { labels: { result: 'no_experiment' }, value: 1 },
        ])
    })

    it('counts a team with no experiments as no_experiment', async () => {
        const step = createMeasureExperimentFlagKeysStep(createMockManager(jest.fn().mockResolvedValue({ '1': null })))

        await step([createInput('$feature_flag_called', 1)])
        await flushMicrotasks()

        expect(await getMetricValues('ingestion_experiment_flag_keys_lookup_total')).toEqual([
            { labels: { result: 'no_experiment' }, value: 1 },
        ])
    })

    it.each([
        ['the chunk has no $feature_flag_called events', '$pageview', { $feature_flag: 'my-flag' }],
        ['the event has no flag key', '$feature_flag_called', {}],
        ['the flag key is not a string', '$feature_flag_called', { $feature_flag: 42 }],
    ])('does not query when %s', async (_name, event, properties) => {
        const manager = createMockManager()
        const step = createMeasureExperimentFlagKeysStep(manager)

        await step([createInput(event, 1, properties)])
        await flushMicrotasks()

        expect(manager.getExperimentFlagKeys).not.toHaveBeenCalled()
    })

    it('passes events through untouched when no manager is configured', async () => {
        const step = createMeasureExperimentFlagKeysStep(undefined)
        const inputs = [createInput('$feature_flag_called', 1)]

        const results = await step(inputs)
        await flushMicrotasks()

        expect(results).toHaveLength(1)
        expect(isOkResult(results[0]) && results[0].value).toBe(inputs[0])
    })

    it('passes every event through unchanged', async () => {
        const step = createMeasureExperimentFlagKeysStep(createMockManager())
        const inputs = [createInput('$feature_flag_called', 1), createInput('$pageview', 1)]

        const results = await step(inputs)

        expect(results).toHaveLength(2)
        results.forEach((result, index) => {
            expect(isOkResult(result)).toBe(true)
            expect(isOkResult(result) && result.value).toBe(inputs[index])
        })
    })

    // Without the step's .catch(), the rejection escapes and Jest fails this test.
    it('swallows a failed lookup instead of raising an unhandled rejection', async () => {
        const manager = createMockManager(jest.fn().mockRejectedValue(new Error('ECONNREFUSED')))
        const step = createMeasureExperimentFlagKeysStep(manager)

        const results = await step([createInput('$feature_flag_called', 1)])
        await flushMicrotasks()

        expect(isOkResult(results[0])).toBe(true)
    })
})
