import { hexToRGBA } from 'lib/utils'

import type { CurrencyCode, GoalLine as SchemaGoalLine, TrendsFilter } from '~/queries/schema/schema-general'

import {
    buildTrendsBarAggregatedSeries,
    buildTrendsBarTimeSeries,
    buildTrendsBarTimeSeriesConfig,
    type TrendsBarResultLike,
} from './trendsBarChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<TrendsBarResultLike> = {}): TrendsBarResultLike => ({
    id: 0,
    label: 'Pageview',
    data: [1, 2, 3, 4, 5],
    ...overrides,
})

describe('buildTrendsBarTimeSeries', () => {
    it('returns one series per result with the result data unchanged', () => {
        const results = [makeResult({ id: 'a', data: [1, 2, 3] }), makeResult({ id: 'b', data: [4, 5, 6] })]
        const series = buildTrendsBarTimeSeries(results, { getColor: () => RED })

        expect(series).toHaveLength(2)
        expect(series.map((s) => s.key)).toEqual(['a', 'b'])
        expect(series[0].data).toEqual([1, 2, 3])
        expect(series[1].data).toEqual([4, 5, 6])
    })

    it.each([
        { compare_label: undefined, expectedColor: RED },
        { compare_label: 'previous' as const, expectedColor: hexToRGBA(RED, 0.5) },
    ])(
        'applies getColor and dims compare-previous to 0.5 alpha (compare_label=$compare_label)',
        ({ compare_label, expectedColor }) => {
            const series = buildTrendsBarTimeSeries([makeResult({ compare_label })], { getColor: () => RED })
            expect(series[0].color).toBe(expectedColor)
        }
    )

    it('marks a series excluded when getHidden returns true', () => {
        const series = buildTrendsBarTimeSeries([makeResult()], {
            getColor: () => RED,
            getHidden: () => true,
        })
        expect(series[0].visibility).toEqual({ excluded: true })
    })

    it('attaches the meta payload returned by buildMeta', () => {
        const meta = { breakdown_value: 'spike', order: 7 }
        const series = buildTrendsBarTimeSeries([makeResult()], {
            getColor: () => RED,
            buildMeta: () => meta,
        })
        expect(series[0].meta).toBe(meta)
    })

    it('falls back to empty string label when result label is null', () => {
        const series = buildTrendsBarTimeSeries([makeResult({ label: null })], { getColor: () => RED })
        expect(series[0].label).toBe('')
    })
})

describe('buildTrendsBarAggregatedSeries', () => {
    const mkResult = (overrides: Partial<TrendsBarResultLike> = {}): TrendsBarResultLike => ({
        id: 0,
        label: 'Pageview',
        data: [],
        aggregated_value: 42,
        ...overrides,
    })

    it('returns labels aligned with results, in the same order', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', aggregated_value: 1 }),
            mkResult({ id: 'b', label: 'B', aggregated_value: 2 }),
            mkResult({ id: 'c', label: 'C', aggregated_value: 3 }),
        ]
        const { labels } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(labels).toEqual(['A', 'B', 'C'])
    })

    it('places each aggregated_value at the index matching its own band — zero everywhere else', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', aggregated_value: 10 }),
            mkResult({ id: 'b', label: 'B', aggregated_value: 20 }),
            mkResult({ id: 'c', label: 'C', aggregated_value: 30 }),
        ]
        const { series } = buildTrendsBarAggregatedSeries(results, { getColor: () => RED })
        expect(series[0].data).toEqual([10, 0, 0])
        expect(series[1].data).toEqual([0, 20, 0])
        expect(series[2].data).toEqual([0, 0, 30])
    })

    it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY, undefined])(
        'replaces non-finite aggregated_value (%p) with 0 at the result index',
        (badValue) => {
            const { series } = buildTrendsBarAggregatedSeries([mkResult({ aggregated_value: badValue })], {
                getColor: () => RED,
            })
            expect(series[0].data).toEqual([0])
        }
    )

    it('passes per-result colors through from getColor', () => {
        const colors = ['#aaa', '#bbb', '#ccc']
        const results = colors.map((_, i) => mkResult({ id: `r${i}` }))
        const { series } = buildTrendsBarAggregatedSeries(results, { getColor: (_r, i) => colors[i] })
        expect(series.map((s) => s.color)).toEqual(colors)
    })

    it('drops hidden results so visible bars are densely packed', () => {
        const results = [
            mkResult({ id: 'a', label: 'A', aggregated_value: 1 }),
            mkResult({ id: 'b', label: 'B', aggregated_value: 2 }),
            mkResult({ id: 'c', label: 'C', aggregated_value: 3 }),
        ]
        const { series, labels } = buildTrendsBarAggregatedSeries(results, {
            getColor: () => RED,
            getHidden: (_r, i) => i === 1,
        })
        expect(labels).toEqual(['A', 'C'])
        expect(series).toHaveLength(2)
        expect(series[0].data).toEqual([1, 0])
        expect(series[1].data).toEqual([0, 3])
    })
})

describe('buildTrendsBarTimeSeriesConfig', () => {
    it.each([
        { isPercentStackView: false, isGrouped: false, expected: 'stacked' },
        { isPercentStackView: false, isGrouped: true, expected: 'grouped' },
        { isPercentStackView: true, isGrouped: false, expected: 'percent' },
        { isPercentStackView: true, isGrouped: true, expected: 'percent' },
    ])(
        'maps isPercentStackView=$isPercentStackView / isGrouped=$isGrouped to barLayout=$expected',
        ({ isPercentStackView, isGrouped, expected }) => {
            const cfg = buildTrendsBarTimeSeriesConfig({ isPercentStackView, isGrouped })
            expect(cfg.barLayout).toBe(expected)
        }
    )

    it.each([
        {
            name: 'builds the xAxis from interval/timezone/allDays',
            input: { interval: 'day' as const, timezone: 'UTC', allDays: ['2024-06-10', '2024-06-11'] },
            expected: { timezone: 'UTC', interval: 'day', allDays: ['2024-06-10', '2024-06-11'] },
        },
        {
            name: 'defaults interval to "day" and allDays to empty when omitted',
            input: {},
            expected: { timezone: undefined, interval: 'day', allDays: [] },
        },
    ])('$name', ({ input, expected }) => {
        const cfg = buildTrendsBarTimeSeriesConfig({ isPercentStackView: false, isGrouped: false, ...input })
        expect(cfg.xAxis).toEqual(expected)
    })

    it('forwards the y-axis from buildTrendsYAxisConfig with showGrid: true', () => {
        const trendsFilter: TrendsFilter = { aggregationAxisFormat: 'duration', aggregationAxisPrefix: '~' }
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            trendsFilter,
            baseCurrency: 'USD' as CurrencyCode,
            yAxisScaleType: 'log10',
        })
        expect(cfg.yAxis).toMatchObject({
            format: 'duration',
            prefix: '~',
            currency: 'USD',
            scale: 'log',
            showGrid: true,
        })
    })

    it('forces percentage format when isPercentStackView is true', () => {
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: true,
            isGrouped: false,
            trendsFilter: { aggregationAxisFormat: 'currency' },
        })
        expect(cfg.yAxis?.format).toBe('percentage')
    })

    it('maps schema goal lines through the shared adapter', () => {
        const goalLines: SchemaGoalLine[] = [{ value: 50, label: 'Target' }]
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            goalLines,
        })
        expect(cfg.goalLines).toEqual([expect.objectContaining({ value: 50, label: 'Target' })])
    })

    it('passes valueLabels and tooltip through unchanged', () => {
        const formatter = (v: number): string => `~${v}`
        const cfg = buildTrendsBarTimeSeriesConfig({
            isPercentStackView: false,
            isGrouped: false,
            valueLabels: { formatter },
            tooltip: { pinnable: true, placement: 'top' },
        })
        expect(cfg.valueLabels).toEqual({ formatter })
        expect(cfg.tooltip).toEqual({ pinnable: true, placement: 'top' })
    })
})
