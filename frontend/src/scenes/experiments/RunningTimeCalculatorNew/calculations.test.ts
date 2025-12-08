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
                numberOfVariants
            )

            expect(recommendedSampleSize).toBeCloseTo(1152, 0)
        })
    })

    // Ratio metric tests
    describe('calculations for RATIO', () => {
        const metric: ExperimentMetric = {
            uuid: uuid(),
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.RATIO,
            numerator: {
                kind: NodeKind.EventsNode,
                event: 'purchase',
                math: ExperimentMetricMathType.TotalCount,
            },
            denominator: {
                kind: NodeKind.EventsNode,
                event: 'page_view',
                math: ExperimentMetricMathType.TotalCount,
            },
        } as ExperimentMetric

        it('calculates baseline value, variance, and recommended sample size correctly', () => {
            /**
             * Realistic scenario: Revenue per order
             *
             * Setup:
             * - 10,000 users (sample size)
             * - Total revenue: $500,000 (numerator sum)
             * - Total orders: 50,000 (denominator sum)
             * - Baseline ratio: $500,000 / 50,000 = $10 per order
             *
             * Variance components (calculated from sums of squares and products):
             * - meanM = 50, varM = 500 (revenue variance per user)
             * - meanD = 5, varD = 5 (order count variance per user)
             * - cov = 10 (positive covariance: more orders → more revenue)
             *
             * Delta method variance:
             * Var(R) = 500/25 + 2500*5/625 - 2*50*10/125
             *        = 20 + 20 - 8
             *        = 32
             *
             * Sample size for 10% MDE:
             * d = 0.10 * 10 = 1
             * N = (16 * 32) / 1² = 512 per variant
             * Total = 512 * 2 = 1024
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 10000,
                sum: 500000, // Σ revenue ($50 per user)
                sum_squares: 30000000, // Σ revenue² (includes variance)
                denominator_sum: 50000, // Σ orders (5 per user)
                denominator_sum_squares: 300000, // Σ orders² (includes variance)
                numerator_denominator_sum_product: 2600000, // Σ(revenue × orders) (includes covariance)
                step_counts: [],
            }

            // Test baseline value calculation
            // Backend reference: posthog/products/experiments/stats/shared/statistics.py:119-124
            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBeCloseTo(10, 4) // $10 per order

            // Test variance calculation using delta method
            // Backend reference: posthog/products/experiments/stats/shared/statistics.py:135-145
            const variance = calculateVarianceFromResults(baselineValue!, metric, baseline)
            expect(variance).not.toBeNull()
            expect(variance).toBeCloseTo(32, 1) // Variance = 32

            // Test sample size calculation
            const numberOfVariants = 2
            const minimumDetectableEffect = 10 // 10% increase

            const recommendedSampleSize = calculateRecommendedSampleSize(
                metric,
                minimumDetectableEffect,
                baselineValue!,
                numberOfVariants,
                baseline
            )

            expect(recommendedSampleSize).not.toBeNull()
            expect(recommendedSampleSize).toBeCloseTo(1024, 0) // 512 per variant * 2
        })

        it('calculates variance correctly with zero covariance', () => {
            /**
             * Test case with zero covariance (independent numerator and denominator)
             *
             * Setup:
             * - 1,000 users
             * - sum = 5,000 (5 per user), sum_squares = 30,000 (variance = 5)
             * - denominator_sum = 10,000 (10 per user), denominator_sum_squares = 105,000 (variance = 5)
             * - product = 50,000 (exactly sum * denominator_sum / n, so cov = 0)
             *
             * Expected variance with cov = 0:
             * Var(R) = 5/100 + 25*5/10000 - 0
             *        = 0.05 + 0.0125
             *        = 0.0625
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 5000,
                sum_squares: 30000,
                denominator_sum: 10000,
                denominator_sum_squares: 105000,
                numerator_denominator_sum_product: 50000, // Exactly meanM * meanD * n (zero cov)
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBeCloseTo(0.5, 4)

            const variance = calculateVarianceFromResults(baselineValue!, metric, baseline)
            expect(variance).toBeCloseTo(0.0625, 5)
        })

        it('calculates variance correctly with high positive covariance', () => {
            /**
             * Test case with high positive covariance
             * Numerator and denominator move together strongly
             * This should reduce variance due to the -2M*Cov term
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 5000, // meanM = 5
                sum_squares: 30000, // varM = 5
                denominator_sum: 10000, // meanD = 10
                denominator_sum_squares: 105000, // varD = 5
                numerator_denominator_sum_product: 52000, // High positive covariance
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            const variance = calculateVarianceFromResults(baselineValue!, metric, baseline)

            // With positive covariance, variance should be lower than zero-cov case
            expect(variance).not.toBeNull()
            expect(variance!).toBeLessThan(0.0625)
        })

        it('returns null when denominator_sum is zero', () => {
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 100,
                sum_squares: 500,
                denominator_sum: 0, // Invalid: division by zero
                denominator_sum_squares: 0,
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBeNull()
        })

        it('returns null when baseline is missing for variance calculation', () => {
            const baselineValue = 0.05
            const variance = calculateVarianceFromResults(baselineValue, metric, undefined)
            expect(variance).toBeNull()
        })

        it('returns null when number_of_samples is zero', () => {
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 0,
                sum: 100,
                sum_squares: 500,
                denominator_sum: 1000,
                denominator_sum_squares: 5000,
                step_counts: [],
            }

            const variance = calculateVarianceFromResults(10, metric, baseline)
            expect(variance).toBeNull()
        })

        it('handles missing denominator_sum_squares gracefully', () => {
            /**
             * Test backward compatibility if denominator_sum_squares is missing
             * Should default to 0, which means denominator variance = 0
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 5000,
                sum_squares: 30000,
                denominator_sum: 10000,
                // denominator_sum_squares missing
                numerator_denominator_sum_product: 50000,
                step_counts: [],
            }

            const variance = calculateVarianceFromResults(0.5, metric, baseline)
            expect(variance).not.toBeNull()
            // Should still calculate, just with varD = 0
        })

        it('handles missing numerator_denominator_sum_product gracefully', () => {
            /**
             * Test backward compatibility if product sum is missing
             * Should default to 0, which means covariance = -meanM * meanD
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 5000,
                sum_squares: 30000,
                denominator_sum: 10000,
                denominator_sum_squares: 105000,
                // numerator_denominator_sum_product missing
                step_counts: [],
            }

            const variance = calculateVarianceFromResults(0.5, metric, baseline)
            expect(variance).not.toBeNull()
            // Should still calculate, covariance will be negative
        })
    })

    // Retention metric tests
    describe('calculations for RETENTION', () => {
        const metric: ExperimentMetric = {
            uuid: uuid(),
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.RETENTION,
            start_event: {
                kind: NodeKind.EventsNode,
                event: 'uploaded_file',
            },
            completion_event: {
                kind: NodeKind.EventsNode,
                event: 'downloaded_file',
            },
            retention_window_start: 0,
            retention_window_end: 360,
            retention_window_unit: 'day',
            start_handling: 'first_seen',
        } as ExperimentMetric

        it('calculates baseline value, variance, and recommended sample size correctly', () => {
            /**
             * Realistic scenario: File download retention
             *
             * Setup:
             * - 10,000 users uploaded files (number_of_samples)
             * - 7,000 users downloaded files (sum - completions)
             * - Retention rate: 7,000 / 10,000 = 70%
             *
             * For retention metrics:
             * - Numerator: binary (0 or 1 per user) - did they complete?
             * - Denominator: always 1 per user (they all started)
             * - denominator_sum = number_of_samples = 10,000
             * - denominator_sum_squares = number_of_samples = 10,000 (since 1² = 1)
             * - numerator_denominator_sum_product = sum = 7,000 (since value × 1 = value)
             *
             * Variance components:
             * - meanM = 0.7 (70% retention)
             * - meanD = 1 (everyone who started)
             * - varM = (sum_squares / n) - meanM² = (7000 / 10000) - 0.49 = 0.7 - 0.49 = 0.21
             * - varD = 0 (denominator is constant 1)
             * - cov = (product / n) - meanM × meanD = (7000 / 10000) - 0.7 × 1 = 0
             *
             * Delta method variance:
             * Var(R) = varM / meanD² + meanM² × varD / meanD⁴ - 2 × meanM × cov / meanD³
             *        = 0.21 / 1 + 0.49 × 0 / 1 - 0
             *        = 0.21
             *
             * Sample size for 10% MDE:
             * d = 0.10 × 0.7 = 0.07
             * N = (16 × 0.21) / 0.07² = 3.36 / 0.0049 ≈ 686 per variant
             * Total = 686 × 2 = 1372
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 10000,
                sum: 7000, // 7,000 users completed (70% retention)
                sum_squares: 7000, // Σ(value²) where value is 0 or 1: 7000×1² + 3000×0² = 7000
                denominator_sum: 10000, // All 10,000 users started
                denominator_sum_squares: 10000, // Σ(1²) = 10,000
                numerator_denominator_sum_product: 7000, // Σ(value × 1) = sum
                step_counts: [],
            }

            // Test baseline value calculation
            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBeCloseTo(0.7, 4) // 70% retention

            // Test variance calculation using delta method
            const variance = calculateVarianceFromResults(baselineValue!, metric, baseline)
            expect(variance).not.toBeNull()
            expect(variance).toBeCloseTo(0.21, 4)

            // Test sample size calculation
            const numberOfVariants = 2
            const minimumDetectableEffect = 10 // 10% increase

            const recommendedSampleSize = calculateRecommendedSampleSize(
                metric,
                minimumDetectableEffect,
                baselineValue!,
                numberOfVariants,
                baseline
            )

            expect(recommendedSampleSize).not.toBeNull()
            expect(recommendedSampleSize).toBeCloseTo(1372, 0)
        })

        it('handles zero retention correctly', () => {
            /**
             * Edge case: No users completed (0% retention)
             * - 1,000 users started
             * - 0 users completed
             * - Retention rate: 0 / 1,000 = 0%
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 0, // Zero completions
                sum_squares: 0,
                denominator_sum: 1000,
                denominator_sum_squares: 1000,
                numerator_denominator_sum_product: 0,
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBe(0) // 0% retention

            const variance = calculateVarianceFromResults(baselineValue!, metric, baseline)
            expect(variance).not.toBeNull()
            // Variance should be 0 since all values are 0
            expect(variance).toBeCloseTo(0, 4)
        })

        it('handles perfect retention correctly', () => {
            /**
             * Edge case: All users completed (100% retention)
             * - 1,000 users started
             * - 1,000 users completed
             * - Retention rate: 1,000 / 1,000 = 100%
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 1000, // All completed
                sum_squares: 1000, // 1000 × 1² = 1000
                denominator_sum: 1000,
                denominator_sum_squares: 1000,
                numerator_denominator_sum_product: 1000,
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBe(1) // 100% retention

            const variance = calculateVarianceFromResults(baselineValue!, metric, baseline)
            expect(variance).not.toBeNull()
            // Variance should be 0 since all values are 1 (no variation)
            expect(variance).toBeCloseTo(0, 4)
        })

        it('returns null when denominator_sum is zero', () => {
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 100,
                sum_squares: 100,
                denominator_sum: 0, // Invalid: no users started
                denominator_sum_squares: 0,
                numerator_denominator_sum_product: 0,
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBeNull()
        })

        it('handles missing denominator fields gracefully', () => {
            /**
             * Test backward compatibility if ratio fields are missing
             * Should return null for variance
             */
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 1000,
                sum: 700,
                sum_squares: 700,
                // denominator fields missing
                step_counts: [],
            }

            const baselineValue = calculateBaselineValue(baseline, metric)
            expect(baselineValue).toBeNull() // Can't calculate without denominator_sum

            const variance = calculateVarianceFromResults(0.7, metric, baseline)
            expect(variance).toBeNull() // Can't calculate variance without baseline
        })
    })
})
