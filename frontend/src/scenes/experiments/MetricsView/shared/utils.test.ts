import type { ExperimentFunnelsQuery, ExperimentMetric, ExperimentTrendsQuery } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import { ExperimentMetricGoal, ExperimentMetricMathType } from '~/types'

import {
    type ExperimentVariantResult,
    formatChanceToWinForGoal,
    formatPValue,
    getChanceToWin,
    getDefaultMetricTitle,
    getMetricColors,
    getMetricTag,
    isWinning,
} from './utils'

describe('getMetricTag', () => {
    it('handles different metric types correctly', () => {
        const experimentMetric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'purchase',
                math: ExperimentMetricMathType.TotalCount,
            },
        }

        const funnelMetric: ExperimentFunnelsQuery = {
            kind: NodeKind.ExperimentFunnelsQuery,
            funnels_query: {
                kind: NodeKind.FunnelsQuery,
                series: [],
            },
        }

        const trendMetric: ExperimentTrendsQuery = {
            kind: NodeKind.ExperimentTrendsQuery,
            count_query: {
                kind: NodeKind.TrendsQuery,
                series: [],
            },
        }

        expect(getMetricTag(experimentMetric)).toBe('Mean')
        expect(getMetricTag(funnelMetric)).toBe('Funnel')
        expect(getMetricTag(trendMetric)).toBe('Trend')
    })
})

describe('getDefaultMetricTitle', () => {
    it('handles ExperimentEventMetricConfig with math and math_property', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.EventsNode,
                event: 'purchase completed',
            },
        }
        expect(getDefaultMetricTitle(metric)).toBe('purchase completed')
    })

    it('returns action name for ExperimentActionMetricConfig', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ActionsNode,
                id: 1,
                name: 'purchase',
            },
        }

        expect(getDefaultMetricTitle(metric)).toBe('purchase')
    })

    it('returns table name for ExperimentDataWarehouseMetricConfig', () => {
        const metric: ExperimentMetric = {
            kind: NodeKind.ExperimentMetric,
            metric_type: ExperimentMetricType.MEAN,
            source: {
                kind: NodeKind.ExperimentDataWarehouseNode,
                table_name: 'purchase_events',
                timestamp_field: 'timestamp',
                events_join_key: 'person_id',
                data_warehouse_join_key: 'person_id',
            },
        }
        expect(getDefaultMetricTitle(metric)).toBe('purchase_events')
    })
})

describe('isWinning', () => {
    const createResult = (credible_interval: [number, number] | undefined): ExperimentVariantResult => ({
        key: 'test',
        sum: 100,
        number_of_samples: 100,
        sum_squares: 100,
        significant: true,
        method: 'bayesian',
        credible_interval,
        chance_to_win: 0.75,
    })

    it('returns true for positive delta with increase goal', () => {
        const result = createResult([0.05, 0.15])
        expect(isWinning(result, ExperimentMetricGoal.Increase)).toBe(true)
    })

    it('returns false for positive delta with decrease goal', () => {
        const result = createResult([0.05, 0.15])
        expect(isWinning(result, ExperimentMetricGoal.Decrease)).toBe(false)
    })

    it('returns false for negative delta with increase goal', () => {
        const result = createResult([-0.15, -0.05])
        expect(isWinning(result, ExperimentMetricGoal.Increase)).toBe(false)
    })

    it('returns true for negative delta with decrease goal', () => {
        const result = createResult([-0.15, -0.05])
        expect(isWinning(result, ExperimentMetricGoal.Decrease)).toBe(true)
    })

    it('returns undefined when no interval is present', () => {
        const result = createResult(undefined)
        expect(isWinning(result, ExperimentMetricGoal.Increase)).toBeUndefined()
        expect(isWinning(result, ExperimentMetricGoal.Decrease)).toBeUndefined()
    })
})

describe('getChanceToWin', () => {
    const createBayesianResult = (chance_to_win: number | undefined): ExperimentVariantResult => ({
        key: 'test',
        sum: 100,
        number_of_samples: 100,
        sum_squares: 100,
        significant: true,
        method: 'bayesian',
        credible_interval: [0.05, 0.15],
        chance_to_win,
    })

    const createFrequentistResult = (): ExperimentVariantResult => ({
        key: 'test',
        sum: 100,
        number_of_samples: 100,
        sum_squares: 100,
        significant: true,
        method: 'frequentist',
        confidence_interval: [0.05, 0.15],
        p_value: 0.03,
    })

    it('returns chance to win as-is for increase goal', () => {
        const result = createBayesianResult(0.75)
        expect(getChanceToWin(result, ExperimentMetricGoal.Increase)).toBe(0.75)
    })

    it('inverts chance to win for decrease goal', () => {
        const result = createBayesianResult(0.75)
        expect(getChanceToWin(result, ExperimentMetricGoal.Decrease)).toBe(0.25)
    })

    it('handles null chance to win', () => {
        const result = createBayesianResult(undefined)
        expect(getChanceToWin(result, ExperimentMetricGoal.Increase)).toBeUndefined()
        expect(getChanceToWin(result, ExperimentMetricGoal.Decrease)).toBeUndefined()
    })

    it('returns undefined for frequentist results', () => {
        const result = createFrequentistResult()
        expect(getChanceToWin(result, ExperimentMetricGoal.Increase)).toBeUndefined()
        expect(getChanceToWin(result, ExperimentMetricGoal.Decrease)).toBeUndefined()
    })
})

describe('formatChanceToWinForGoal', () => {
    const createResult = (chance_to_win: number): ExperimentVariantResult => ({
        key: 'test',
        sum: 100,
        number_of_samples: 100,
        sum_squares: 100,
        significant: true,
        method: 'bayesian',
        credible_interval: [0.05, 0.15],
        chance_to_win,
    })

    it('formats chance to win for increase goal', () => {
        const result = createResult(0.756)
        expect(formatChanceToWinForGoal(result, ExperimentMetricGoal.Increase)).toBe('75.6%')
    })

    it('formats inverted chance to win for decrease goal', () => {
        const result = createResult(0.756)
        expect(formatChanceToWinForGoal(result, ExperimentMetricGoal.Decrease)).toBe('24.4%')
    })

    it('handles very high chances', () => {
        const result = createResult(0.9995)
        expect(formatChanceToWinForGoal(result, ExperimentMetricGoal.Increase)).toBe('> 99.9%')
        expect(formatChanceToWinForGoal(result, ExperimentMetricGoal.Decrease)).toBe('< 0.1%')
    })

    it('handles very low chances', () => {
        const result = createResult(0.0005)
        expect(formatChanceToWinForGoal(result, ExperimentMetricGoal.Increase)).toBe('< 0.1%')
        expect(formatChanceToWinForGoal(result, ExperimentMetricGoal.Decrease)).toBe('> 99.9%')
    })
})

describe('getMetricColors', () => {
    const colors = {
        BAR_POSITIVE: '#00FF00',
        BAR_NEGATIVE: '#FF0000',
    }

    it('returns normal colors for increase goal', () => {
        const result = getMetricColors(colors, ExperimentMetricGoal.Increase)
        expect(result.positive).toBe('#00FF00')
        expect(result.negative).toBe('#FF0000')
    })

    it('swaps colors for decrease goal', () => {
        const result = getMetricColors(colors, ExperimentMetricGoal.Decrease)
        expect(result.positive).toBe('#FF0000')
        expect(result.negative).toBe('#00FF00')
    })
})

describe('formatPValue', () => {
    it('returns "—" for null', () => {
        expect(formatPValue(null)).toBe('—')
    })

    it('returns "—" for undefined', () => {
        expect(formatPValue(undefined)).toBe('—')
    })

    it('returns "< 0.001" for very small p-values', () => {
        expect(formatPValue(0.0001)).toBe('< 0.001')
        expect(formatPValue(0.00001)).toBe('< 0.001')
        expect(formatPValue(4.196532010780629e-11)).toBe('< 0.001')
        expect(formatPValue(1e-100)).toBe('< 0.001')
    })

    it('returns 4 decimal places for p-values between 0.001 and 0.01', () => {
        expect(formatPValue(0.001)).toBe('0.0010')
        expect(formatPValue(0.005)).toBe('0.0050')
        expect(formatPValue(0.009)).toBe('0.0090')
        expect(formatPValue(0.00999)).toBe('0.0100')
    })

    it('returns 3 decimal places for p-values >= 0.01', () => {
        expect(formatPValue(0.01)).toBe('0.010')
        expect(formatPValue(0.05)).toBe('0.050')
        expect(formatPValue(0.1)).toBe('0.100')
        expect(formatPValue(0.5)).toBe('0.500')
        expect(formatPValue(0.999)).toBe('0.999')
    })

    it('handles edge case of exactly 0.001', () => {
        expect(formatPValue(0.001)).toBe('0.0010')
    })

    it('handles edge case of exactly 0.01', () => {
        expect(formatPValue(0.01)).toBe('0.010')
    })

    it('handles p-value of 1', () => {
        expect(formatPValue(1)).toBe('1.000')
    })

    // Critical test case: p-value of 0 should now be formatted properly
    it('returns "< 0.001" for p-value of 0', () => {
        expect(formatPValue(0)).toBe('< 0.001')
    })

    // Edge case: very close to 0 but not exactly 0
    it('returns "< 0.001" for Number.MIN_VALUE', () => {
        expect(formatPValue(Number.MIN_VALUE)).toBe('< 0.001')
    })
})
