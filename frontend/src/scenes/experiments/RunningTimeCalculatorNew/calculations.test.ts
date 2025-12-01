import { uuid } from 'lib/utils'

import {
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    ExperimentMetricType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { Experiment, ExperimentMetricMathType, FeatureFlagBasicType } from '~/types'

import { calculateBaselineValue, calculateRecommendedSampleSize, calculateVarianceFromResults } from './calculations'

describe('calculations', () => {
    // Should match https://docs.google.com/spreadsheets/d/11alyC8n7uqewZFLKfV4UAbW-0zH__EdV_Hrk2OQ4140/edit?gid=777532876#gid=777532876
    describe('calculations for MEAN total count', () => {
        const metric: ExperimentMetric = {
            uuid: uuid(),
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'experiment created',
                math: ExperimentMetricMathType.TotalCount,
            },
        }

        const experiment = {
            feature_flag: {
                filters: {
                    multivariate: {
                        variants: [
                            {
                                key: 'control',
                                rollout_percentage: 50,
                            },
                            {
                                key: 'test',
                                rollout_percentage: 50,
                            },
                        ],
                    },
                },
            } as unknown as FeatureFlagBasicType,
        } as Partial<Experiment> as Experiment

        it('calculates baseline value, variance, and recommended sample size correctly', () => {
            // Old test input: { uniqueUsers: 14000, averageEventsPerUser: 4 }
            // New baseline format: sum = uniqueUsers * averageEventsPerUser
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 14000,
                sum: 56000, // 14000 * 4
                sum_squares: 0, // Not used
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBe(4) // averageEventsPerUser

            const variance = calculateVarianceFromResults(baselineValue!, metric)
            expect(variance).toBe(8) // VARIANCE_SCALING_FACTOR_TOTAL_COUNT (2) * 4

            const numberOfVariants = experiment.feature_flag?.filters.multivariate?.variants.length ?? 2
            const minimumDetectableEffect = 5

            const recommendedSampleSize = calculateRecommendedSampleSize(
                metric,
                minimumDetectableEffect,
                baselineValue!,
                variance,
                numberOfVariants
            )

            expect(recommendedSampleSize).toBeCloseTo(6400, 0)
        })
    })

    // Should match https://docs.google.com/spreadsheets/d/11alyC8n7uqewZFLKfV4UAbW-0zH__EdV_Hrk2OQ4140/edit?gid=2067479228#gid=2067479228
    describe('calculations for MEAN sum', () => {
        const metric: ExperimentMetric = {
            uuid: uuid(),
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'experiment created',
                math: ExperimentMetricMathType.Sum,
            },
        }

        const experiment = {
            feature_flag: {
                filters: {
                    multivariate: {
                        variants: [
                            {
                                key: 'control',
                                rollout_percentage: 50,
                            },
                            {
                                key: 'test',
                                rollout_percentage: 50,
                            },
                        ],
                    },
                },
            } as unknown as FeatureFlagBasicType,
        } as Partial<Experiment> as Experiment

        it('calculates baseline value, variance, and recommended sample size correctly', () => {
            // Old test input: { uniqueUsers: 14000, averagePropertyValuePerUser: 50 }
            // New baseline format: sum = uniqueUsers * averagePropertyValuePerUser
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 14000,
                sum: 700000, // 14000 * 50
                sum_squares: 0, // Not used
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBe(50) // averagePropertyValuePerUser

            const variance = calculateVarianceFromResults(baselineValue!, metric)
            expect(variance).toBeCloseTo(625, 0) // VARIANCE_SCALING_FACTOR_SUM (0.25) * 50^2

            const numberOfVariants = experiment.feature_flag?.filters.multivariate?.variants.length ?? 2
            const minimumDetectableEffect = 5

            const recommendedSampleSize = calculateRecommendedSampleSize(
                metric,
                minimumDetectableEffect,
                baselineValue!,
                variance,
                numberOfVariants
            )

            expect(recommendedSampleSize).toBeCloseTo(3200, 0)
        })
    })

    // Should match https://docs.google.com/spreadsheets/d/11alyC8n7uqewZFLKfV4UAbW-0zH__EdV_Hrk2OQ4140/edit?gid=0#gid=0
    describe('calculations for FUNNEL', () => {
        const metric: ExperimentMetric = {
            uuid: uuid(),
            metric_type: ExperimentMetricType.FUNNEL,
            series: [
                {
                    kind: NodeKind.EventsNode,
                    event: 'first_step',
                },
                {
                    kind: NodeKind.EventsNode,
                    event: 'final_step',
                },
            ],
        } as ExperimentMetric

        const experiment = {
            feature_flag: {
                filters: {
                    multivariate: {
                        variants: [
                            {
                                key: 'control',
                                rollout_percentage: 50,
                            },
                            {
                                key: 'test',
                                rollout_percentage: 50,
                            },
                        ],
                    },
                },
            } as unknown as FeatureFlagBasicType,
        } as Partial<Experiment> as Experiment

        it('calculates baseline value and recommended sample size correctly', () => {
            // Old test input: { uniqueUsers: 1000, automaticConversionRateDecimal: 0.1 }
            // New baseline format: step_counts where last/total = conversion rate
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 100, // number of conversions
                sum_squares: 0, // Not used
                step_counts: [1000, 100], // first step count, final step count
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBe(0.1) // conversionRate = 100/1000

            // Funnel metrics don't use separate variance calculation
            const variance = calculateVarianceFromResults(baselineValue!, metric)
            expect(variance).toBeNull()

            const numberOfVariants = experiment.feature_flag?.filters.multivariate?.variants.length ?? 2
            const minimumDetectableEffect = 50

            const recommendedSampleSize = calculateRecommendedSampleSize(
                metric,
                minimumDetectableEffect,
                baselineValue!,
                variance,
                numberOfVariants
            )

            expect(recommendedSampleSize).toBeCloseTo(1152, 0)
        })
    })
})
