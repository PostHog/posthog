import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
import EXPERIMENT_V3_WITH_ONE_EXPERIMENT_QUERY from '~/mocks/fixtures/api/experiments/_experiment_v3_with_one_metric.json'
import { Experiment } from '~/types'

import { getEventPropertiesForExperiment } from './eventUsageLogic'

describe('getEventPropertiesForExperiment', () => {
    it('returns the correct event properties for an experiment', () => {
        // Transform null to undefined where needed
        const experiment = {
            ...experimentJson,
            created_by: { ...experimentJson.created_by, hedgehog_config: undefined },
            holdout: undefined,
        } as Experiment
        expect(getEventPropertiesForExperiment(experiment)).toEqual({
            id: 90,
            name: 'jan-16-running',
            type: 'product',
            parameters: {
                feature_flag_variants: [
                    {
                        key: 'control',
                        rollout_percentage: 50,
                    },
                    {
                        key: 'test',
                        rollout_percentage: 50,
                    },
                ],
                recommended_sample_size: 0,
                recommended_running_time: 0,
                minimum_detectable_effect: 1,
            },
            metrics: [
                { kind: 'ExperimentFunnelsQuery', steps_count: 2, filter_test_accounts: true },
                { kind: 'ExperimentTrendsQuery', series_kind: 'EventsNode', filter_test_accounts: true },
            ],
            secondary_metrics: [
                { kind: 'ExperimentTrendsQuery', series_kind: 'EventsNode', filter_test_accounts: true },
                { kind: 'ExperimentTrendsQuery', series_kind: 'EventsNode', filter_test_accounts: true },
            ],
            metrics_count: 2,
            secondary_metrics_count: 2,
            saved_metrics_count: 2,
        })
    })

    it('returns the correct event properties for a v3 experiment with one metric', () => {
        const experiment = {
            ...EXPERIMENT_V3_WITH_ONE_EXPERIMENT_QUERY,
            description: undefined,
        } as Experiment
        expect(getEventPropertiesForExperiment(experiment)).toEqual({
            id: 67,
            name: 'storybook-experiment-3',
            type: 'product',
            parameters: {
                feature_flag_variants: [
                    { key: 'control', rollout_percentage: 34 },
                    { key: 'test-1', rollout_percentage: 33 },
                    { key: 'test-2', rollout_percentage: 33 },
                ],
                recommended_sample_size: 0,
                recommended_running_time: 0,
                minimum_detectable_effect: 1,
            },
            metrics: [{ kind: 'ExperimentMetric', metric_type: 'mean' }],
            secondary_metrics: [],
            metrics_count: 1,
            secondary_metrics_count: 0,
            saved_metrics_count: 0,
        })
    })
})
