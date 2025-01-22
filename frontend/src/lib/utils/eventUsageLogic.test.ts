import experimentJson from '~/mocks/fixtures/api/experiments/_experiment_launched_with_funnel_and_trends.json'
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
                { kind: 'funnel', steps_count: 2 },
                { kind: 'trend', series_type: 'events' },
            ],
            secondary_metrics: [
                { kind: 'trend', series_type: 'events' },
                { kind: 'trend', series_type: 'events' },
            ],
            metrics_count: 2,
            secondary_metrics_count: 2,
            saved_metrics_count: 2,
        })
    })
})
