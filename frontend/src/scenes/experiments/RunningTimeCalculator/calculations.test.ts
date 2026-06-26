import { uuid } from 'lib/utils/dom'

import {
    CachedNewExperimentQueryResponse,
    ExperimentMetric,
    ExperimentMetricType,
    NodeKind,
} from '~/queries/schema/schema-general'
import { ExperimentMetricMathType } from '~/types'

import {
    baselineStatsFromResults,
    calculateCurrentExposures,
    calculateDaysElapsed,
    calculateExposureRate,
    getCalculatorMetricType,
} from './calculations'

// The sample-size / variance math is verified in the backend
// (products/experiments/backend/test/test_running_time_calculator.py). These tests
// cover the client-side helpers that classify metrics and read live experiment state.
describe('running time calculations', () => {
    describe('getCalculatorMetricType', () => {
        const meanMetric = (math: ExperimentMetricMathType): ExperimentMetric =>
            ({
                uuid: uuid(),
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.MEAN,
                source: { kind: NodeKind.EventsNode, event: 'evt', math },
            }) as ExperimentMetric

        it('classifies mean count', () => {
            expect(getCalculatorMetricType(meanMetric(ExperimentMetricMathType.TotalCount))).toBe('mean_count')
        })

        it('classifies mean sum', () => {
            expect(getCalculatorMetricType(meanMetric(ExperimentMetricMathType.Sum))).toBe('mean_sum_or_avg')
        })

        it('classifies funnel', () => {
            const metric = {
                uuid: uuid(),
                metric_type: ExperimentMetricType.FUNNEL,
                series: [{ kind: NodeKind.EventsNode, event: 'step' }],
            } as ExperimentMetric
            expect(getCalculatorMetricType(metric)).toBe('funnel')
        })

        it('classifies ratio', () => {
            const metric = {
                uuid: uuid(),
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.RATIO,
                numerator: { kind: NodeKind.EventsNode, event: 'purchase' },
                denominator: { kind: NodeKind.EventsNode, event: 'page_view' },
            } as ExperimentMetric
            expect(getCalculatorMetricType(metric)).toBe('ratio')
        })

        it('classifies retention', () => {
            const metric = {
                uuid: uuid(),
                kind: NodeKind.ExperimentMetric,
                metric_type: ExperimentMetricType.RETENTION,
                start_event: { kind: NodeKind.EventsNode, event: 'uploaded' },
                completion_event: { kind: NodeKind.EventsNode, event: 'downloaded' },
            } as ExperimentMetric
            expect(getCalculatorMetricType(metric)).toBe('retention')
        })
    })

    describe('baselineStatsFromResults', () => {
        it('maps the results baseline into the request shape', () => {
            const baseline: CachedNewExperimentQueryResponse['baseline'] = {
                key: 'control',
                number_of_samples: 10000,
                sum: 500000,
                sum_squares: 30000000,
                denominator_sum: 50000,
                denominator_sum_squares: 300000,
                numerator_denominator_sum_product: 2600000,
                step_counts: [1000, 100],
            }
            expect(baselineStatsFromResults(baseline)).toEqual({
                number_of_samples: 10000,
                sum: 500000,
                sum_squares: 30000000,
                denominator_sum: 50000,
                denominator_sum_squares: 300000,
                numerator_denominator_sum_product: 2600000,
                step_counts: [1000, 100],
            })
        })
    })

    describe('calculateCurrentExposures', () => {
        it('sums baseline and variant sample counts', () => {
            const results = {
                baseline: { number_of_samples: 1000 },
                variant_results: [{ number_of_samples: 900 }, { number_of_samples: 1100 }],
            } as CachedNewExperimentQueryResponse
            expect(calculateCurrentExposures(results)).toBe(3000)
        })

        it('returns null without results', () => {
            expect(calculateCurrentExposures(null)).toBeNull()
        })
    })

    describe('calculateExposureRate', () => {
        it('returns exposures per day', () => {
            expect(calculateExposureRate(1000, 10)).toBe(100)
        })

        it('returns null below the minimum elapsed window', () => {
            expect(calculateExposureRate(1000, 0.05)).toBeNull()
        })

        it('returns null without exposures', () => {
            expect(calculateExposureRate(null, 10)).toBeNull()
        })
    })

    describe('calculateDaysElapsed', () => {
        it('returns null without a start date', () => {
            expect(calculateDaysElapsed(null)).toBeNull()
        })

        it('returns a positive number for a past start date', () => {
            const elapsed = calculateDaysElapsed('2020-01-01')
            expect(elapsed).not.toBeNull()
            expect(elapsed!).toBeGreaterThan(0)
        })
    })
})
