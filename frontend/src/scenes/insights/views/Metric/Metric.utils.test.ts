import { type MetricChange } from '@posthog/quill-charts'

import { IntervalType } from '~/types'

import {
    computeMetricChange,
    computeMetricSummary,
    computeMetricSummaryChange,
    getMetricChangeTooltip,
    type MetricSeriesSummary,
    MetricSummary,
    selectCurrentSeries,
    selectPreviousSeriesSummary,
} from './Metric.utils'

describe('computeMetricChange', () => {
    const cases: { name: string; data: number[] | undefined; expected: MetricChange | null | undefined }[] = [
        { name: 'undefined data → no change', data: undefined, expected: undefined },
        { name: 'empty series → no change', data: [], expected: undefined },
        { name: 'single point → no change', data: [5], expected: undefined },
        { name: 'drops below two finite points → no change', data: [NaN, Infinity], expected: undefined },
        { name: 'increase', data: [100, 150], expected: { value: 50 } },
        { name: 'decrease', data: [200, 100], expected: { value: -50 } },
        { name: 'zero start, positive end → +∞', data: [0, 50], expected: { value: 1, label: '∞' } },
        { name: 'zero start, zero end → no movement', data: [0, 0], expected: null },
        { name: 'zero start, negative end → -∞', data: [0, -5], expected: { value: -1, label: '∞' } },
        { name: 'just below cap → real % with no ∞ label', data: [100, 10000], expected: { value: 9900 } },
        { name: 'exactly at cap → ∞', data: [1, 101], expected: { value: 10000, label: '∞' } },
        { name: 'over cap → ∞ (value preserved)', data: [1, 100000], expected: { value: 9999900, label: '∞' } },
        {
            name: 'negative over cap → ∞ (Math.abs on decreases)',
            data: [100, -10000],
            expected: { value: -10100, label: '∞' },
        },
        { name: 'non-finite values filtered out', data: [NaN, 100, 200], expected: { value: 100 } },
        { name: 'negative start increasing', data: [-100, -50], expected: { value: 50 } },
    ]

    it.each(cases)('$name', ({ data, expected }) => {
        expect(computeMetricChange(data)).toEqual(expected)
    })
})

describe('computeMetricSummary', () => {
    const cases: {
        name: string
        summary: MetricSummary
        total: number
        data: number[] | undefined
        expected: number
    }[] = [
        {
            name: 'total returns the supplied aggregate',
            summary: 'total',
            total: 600,
            data: [100, 200, 300],
            expected: 600,
        },
        {
            name: 'average is the mean of finite points',
            summary: 'average',
            total: 600,
            data: [100, 200, 300],
            expected: 200,
        },
        {
            name: 'latest is the last finite point',
            summary: 'latest',
            total: 600,
            data: [100, 200, 300],
            expected: 300,
        },
        {
            name: 'average ignores non-finite points',
            summary: 'average',
            total: 0,
            data: [NaN, 100, 200],
            expected: 150,
        },
        {
            name: 'latest ignores a trailing non-finite point',
            summary: 'latest',
            total: 0,
            data: [100, 200, NaN],
            expected: 200,
        },
        {
            name: 'average falls back to total with no finite data',
            summary: 'average',
            total: 42,
            data: [],
            expected: 42,
        },
        {
            name: 'latest falls back to total with undefined data',
            summary: 'latest',
            total: 42,
            data: undefined,
            expected: 42,
        },
    ]

    it.each(cases)('$name', ({ summary, total, data, expected }) => {
        expect(computeMetricSummary(summary, total, data)).toBe(expected)
    })
})

describe('computeMetricSummaryChange', () => {
    const current = { total: 600, data: [100, 200, 300] }

    const cases: {
        name: string
        summary: MetricSummary
        previous: { total: number; data: number[] | undefined } | undefined
        expected: MetricChange | null | undefined
    }[] = [
        {
            name: 'latest always uses first→last of the current series, ignoring the previous period',
            summary: 'latest',
            previous: { total: 300, data: [50, 100, 150] },
            expected: { value: 200 },
        },
        {
            name: 'total without a previous period falls back to first→last',
            summary: 'total',
            previous: undefined,
            expected: { value: 200 },
        },
        {
            name: 'average without a previous period falls back to first→last',
            summary: 'average',
            previous: undefined,
            expected: { value: 200 },
        },
        {
            name: 'total vs previous total when a comparison period is present',
            summary: 'total',
            previous: { total: 400, data: [100, 100, 200] },
            expected: { value: 50 },
        },
        {
            name: 'average vs previous average when a comparison period is present',
            summary: 'average',
            previous: { total: 300, data: [100, 100, 100] },
            expected: { value: 100 },
        },
        {
            name: 'previous total of zero reads as ∞',
            summary: 'total',
            previous: { total: 0, data: [] },
            expected: { value: 1, label: '∞' },
        },
        {
            name: 'average with no finite previous points yields no pill',
            summary: 'average',
            previous: { total: 0, data: [NaN] },
            expected: undefined,
        },
    ]

    it.each(cases)('$name', ({ summary, previous, expected }) => {
        expect(computeMetricSummaryChange(summary, current, previous)).toEqual(expected)
    })
})

describe('selectPreviousSeriesSummary', () => {
    const current = { count: 600, data: [100, 200, 300], compare_label: 'current' }
    const previous = { count: 300, data: [50, 100, 150], compare_label: 'previous' }

    const cases: {
        name: string
        results: { count: number; data: number[]; compare_label?: string }[] | undefined
        expected: MetricSeriesSummary | undefined
    }[] = [
        { name: 'undefined results → no previous', results: undefined, expected: undefined },
        { name: 'no previous-labelled series → no previous', results: [current], expected: undefined },
        {
            name: 'picks the previous-labelled series',
            results: [current, previous],
            expected: { total: 300, data: [50, 100, 150] },
        },
        {
            name: 'matches by compare_label, not array position',
            results: [previous, current],
            expected: { total: 300, data: [50, 100, 150] },
        },
    ]

    it.each(cases)('$name', ({ results, expected }) => {
        expect(selectPreviousSeriesSummary(results)).toEqual(expected)
    })
})

describe('selectCurrentSeries', () => {
    const current = { count: 600, data: [100, 200, 300], compare_label: 'current' }
    const previous = { count: 300, data: [50, 100, 150], compare_label: 'previous' }
    const unlabelled = { count: 600, data: [100, 200, 300] }

    const cases: {
        name: string
        results: { count: number; data: number[]; compare_label?: string }[] | undefined
        expected: { count: number; data: number[]; compare_label?: string } | undefined
    }[] = [
        { name: 'undefined results → undefined', results: undefined, expected: undefined },
        { name: 'single unlabelled series (no comparison) → that series', results: [unlabelled], expected: unlabelled },
        { name: 'picks current by compare_label, not array position', results: [previous, current], expected: current },
    ]

    it.each(cases)('$name', ({ results, expected }) => {
        expect(selectCurrentSeries(results)).toEqual(expected)
    })
})

describe('getMetricChangeTooltip', () => {
    const firstLast = (noun: string): string =>
        `Comparing the first ${noun}'s value to the most recent ${noun}'s value.`

    const cases: {
        name: string
        summary: MetricSummary
        hasComparison: boolean
        interval: IntervalType | null | undefined
        expected: string
    }[] = [
        {
            name: 'total vs previous period',
            summary: 'total',
            hasComparison: true,
            interval: 'day',
            expected: "Comparing this period's total to the previous period's total.",
        },
        {
            name: 'average vs previous period',
            summary: 'average',
            hasComparison: true,
            interval: 'day',
            expected: "Comparing this period's average to the previous period's average.",
        },
        {
            name: 'latest ignores the comparison period',
            summary: 'latest',
            hasComparison: true,
            interval: 'day',
            expected: firstLast('day'),
        },
        {
            name: 'total falls back to first→last without a comparison',
            summary: 'total',
            hasComparison: false,
            interval: 'day',
            expected: firstLast('day'),
        },
        {
            name: 'non-day interval flows into the noun',
            summary: 'latest',
            hasComparison: false,
            interval: 'hour',
            expected: firstLast('hour'),
        },
        {
            name: 'missing interval falls back to "day"',
            summary: 'latest',
            hasComparison: false,
            interval: null,
            expected: firstLast('day'),
        },
    ]

    it.each(cases)('$name', ({ summary, hasComparison, interval, expected }) => {
        expect(getMetricChangeTooltip(summary, hasComparison, interval)).toBe(expected)
    })
})
