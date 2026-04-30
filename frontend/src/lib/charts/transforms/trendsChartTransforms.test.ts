import { DEFAULT_Y_AXIS_ID, type Series } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

import { ChartDisplayType } from '~/types'

import {
    buildMainTrendsSeries,
    buildTrendsChartConfig,
    buildTrendsSeries,
    type TrendsResultLike,
} from './trendsChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<TrendsResultLike> = {}): TrendsResultLike => ({
    id: 0,
    label: 'Pageview',
    data: [1, 2, 3, 4, 5],
    ...overrides,
})

const lowerDataOf = (s: Series): number[] => (s.fill as { lowerData: number[] }).lowerData

describe('trendsChartTransforms', () => {
    describe('buildMainTrendsSeries', () => {
        it('builds a single main series with no compare and no in-progress tail', () => {
            const built = buildMainTrendsSeries(makeResult(), 0, { getColor: () => RED })

            expect(built.baseColor).toBe(RED)
            expect(built.dashedFromIndex).toBeUndefined()
            expect(built.excluded).toBe(false)
            expect(built.main).toMatchObject({
                key: '0',
                label: 'Pageview',
                data: [1, 2, 3, 4, 5],
                color: RED,
                yAxisId: DEFAULT_Y_AXIS_ID,
            })
            expect(built.main.stroke).toBeUndefined()
            expect(built.main.fill).toBeUndefined()
            expect(built.main.visibility).toBeUndefined()
        })

        it('dims compare-previous series colors to 0.5 alpha', () => {
            const built = buildMainTrendsSeries(makeResult({ compare: true, compare_label: 'previous' }), 0, {
                getColor: () => RED,
            })

            expect(built.baseColor).toBe(RED)
            expect(built.main.color).toBe(hexToRGBA(RED, 0.5))
        })

        it('sets dashedFromIndex on active series and skips it on compare-previous', () => {
            const data = [1, 2, 3, 4, 5, 6, 7]
            const opts = { getColor: () => RED, incompletenessOffsetFromEnd: -2 }

            const active = buildMainTrendsSeries(makeResult({ data, compare: true, compare_label: 'current' }), 0, opts)
            const previous = buildMainTrendsSeries(
                makeResult({ data, compare: true, compare_label: 'previous' }),
                1,
                opts
            )

            expect(active.dashedFromIndex).toBe(5)
            expect(active.main.stroke).toEqual({ partial: { fromIndex: 5 } })
            expect(previous.dashedFromIndex).toBeUndefined()
            expect(previous.main.stroke).toBeUndefined()
        })

        it('skips the dashed tail entirely for stickiness', () => {
            const built = buildMainTrendsSeries(makeResult({ data: [1, 2, 3, 4, 5, 6, 7] }), 0, {
                getColor: () => RED,
                incompletenessOffsetFromEnd: -2,
                isStickiness: true,
            })

            expect(built.dashedFromIndex).toBeUndefined()
            expect(built.main.stroke).toBeUndefined()
        })

        it('attaches an empty fill object for ActionsAreaGraph display', () => {
            const built = buildMainTrendsSeries(makeResult(), 0, {
                getColor: () => RED,
                display: ChartDisplayType.ActionsAreaGraph,
            })
            // Truthy presence (chart treats fill presence as opt-in), but no overrides.
            expect(built.main.fill).toEqual({})
        })

        it('marks a series excluded when getHidden returns true', () => {
            const built = buildMainTrendsSeries(makeResult(), 0, {
                getColor: () => RED,
                getHidden: () => true,
            })

            expect(built.excluded).toBe(true)
            expect(built.main.visibility).toEqual({ excluded: true })
        })

        it('attaches the meta payload returned by buildMeta', () => {
            const meta = { breakdown_value: 'spike', order: 7 }
            const built = buildMainTrendsSeries(makeResult(), 0, {
                getColor: () => RED,
                buildMeta: () => meta,
            })

            expect(built.main.meta).toBe(meta)
        })

        it('falls back to empty string label when result has none', () => {
            const built = buildMainTrendsSeries(makeResult({ label: null }), 0, { getColor: () => RED })
            expect(built.main.label).toBe('')
        })

        it('keeps index 0 on the default y-axis even when showMultipleYAxes is true', () => {
            const built = buildMainTrendsSeries(makeResult(), 0, { getColor: () => RED, showMultipleYAxes: true })
            expect(built.main.yAxisId).toBe(DEFAULT_Y_AXIS_ID)
        })

        it('skips the dashed tail when incompletenessOffsetFromEnd is 0', () => {
            const built = buildMainTrendsSeries(makeResult({ data: [1, 2, 3] }), 0, {
                getColor: () => RED,
                incompletenessOffsetFromEnd: 0,
            })
            expect(built.dashedFromIndex).toBeUndefined()
        })

        it('passes the result index through to getColor and buildMeta', () => {
            const getColor = jest.fn(() => RED)
            const buildMeta = jest.fn(() => ({}))
            buildMainTrendsSeries(makeResult(), 7, { getColor, buildMeta })
            expect(getColor).toHaveBeenCalledWith(expect.anything(), 7)
            expect(buildMeta).toHaveBeenCalledWith(expect.anything(), 7)
        })
    })

    describe('buildTrendsSeries', () => {
        it('returns one main series per result when no derived series flags are set', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' })]
            const series = buildTrendsSeries(results, { getColor: () => RED })

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.key)).toEqual(['a', 'b'])
        })

        it('assigns yAxisIds [left, y1, y2] across three results when showMultipleYAxes is true', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' }), makeResult({ id: 'c' })]
            const series = buildTrendsSeries(results, { getColor: () => RED, showMultipleYAxes: true })

            expect(series.map((s) => s.yAxisId)).toEqual([DEFAULT_Y_AXIS_ID, 'y1', 'y2'])
        })

        describe('confidence intervals', () => {
            const ciOpts = {
                getColor: (): string => RED,
                showConfidenceIntervals: true,
                confidenceLevel: 95,
            }

            it('emits a CI series with key, label, color, yAxisId, and meta from the main series', () => {
                const meta = { breakdown_value: 'a' }
                const series = buildTrendsSeries([makeResult({ id: 7 })], {
                    ...ciOpts,
                    buildMeta: () => meta,
                })

                expect(series).toHaveLength(2)
                expect(series[1]).toMatchObject({
                    key: '7__ci',
                    label: 'Pageview (CI)',
                    color: RED,
                    yAxisId: DEFAULT_Y_AXIS_ID,
                    meta,
                })
                expect(series[1].data?.length).toBe(5)
                expect(series[1].fill).toMatchObject({ opacity: 0.2 })
                expect(lowerDataOf(series[1]).length).toBe(5)
            })

            it('passes confidenceLevel through to ciRanges as a fraction', () => {
                const [s95] = buildTrendsSeries([makeResult()], { ...ciOpts, confidenceLevel: 95 }).slice(1)
                const [s50] = buildTrendsSeries([makeResult()], { ...ciOpts, confidenceLevel: 50 }).slice(1)

                expect(lowerDataOf(s95)[0]).not.toBe(lowerDataOf(s50)[0])
            })

            it('hides CI series when its main is excluded but keeps it visible from tooltip/value-labels', () => {
                const series = buildTrendsSeries([makeResult()], { ...ciOpts, getHidden: () => true })

                expect(series[1].visibility).toEqual({ excluded: true, fromTooltip: true, fromValueLabels: true })
            })

            it('omits CI series entirely when showConfidenceIntervals is false', () => {
                const series = buildTrendsSeries([makeResult()], { getColor: () => RED })
                expect(series).toHaveLength(1)
            })

            it('defaults confidenceLevel to 95 when undefined', () => {
                const explicit = buildTrendsSeries([makeResult()], { ...ciOpts, confidenceLevel: 95 })[1]
                const defaulted = buildTrendsSeries([makeResult()], {
                    getColor: () => RED,
                    showConfidenceIntervals: true,
                })[1]
                expect(lowerDataOf(defaulted)).toEqual(lowerDataOf(explicit))
            })
        })

        describe('moving average', () => {
            const maOpts = {
                getColor: (): string => RED,
                showMovingAverage: true,
                movingAverageIntervals: 3,
            }

            it('emits a moving-average series when data is at least as long as the interval', () => {
                const series = buildTrendsSeries([makeResult({ id: 9, data: [1, 2, 3, 4, 5] })], maOpts)

                expect(series).toHaveLength(2)
                expect(series[1]).toMatchObject({
                    key: '9-ma',
                    label: 'Pageview (Moving avg)',
                    color: RED,
                    yAxisId: DEFAULT_Y_AXIS_ID,
                    stroke: { pattern: [10, 3] },
                    visibility: { fromTooltip: true, fromStack: true },
                })
                expect(series[1].data?.length).toBe(5)
            })

            it('skips the MA series when data is shorter than the interval', () => {
                const series = buildTrendsSeries([makeResult({ data: [1, 2] })], maOpts)
                expect(series).toHaveLength(1)
            })

            it('skips the MA series when movingAverageIntervals is undefined', () => {
                const series = buildTrendsSeries([makeResult()], {
                    getColor: () => RED,
                    showMovingAverage: true,
                })
                expect(series).toHaveLength(1)
            })

            it('skips the MA series when showMovingAverage is false', () => {
                const series = buildTrendsSeries([makeResult()], {
                    getColor: () => RED,
                    movingAverageIntervals: 3,
                })
                expect(series).toHaveLength(1)
            })
        })

        describe('trend lines', () => {
            const tlOpts = { getColor: (): string => RED, showTrendLines: true }

            it('emits a raw trend-line series with the result label and dimmed base color', () => {
                const series = buildTrendsSeries([makeResult({ id: 4 })], tlOpts)

                expect(series).toHaveLength(2)
                expect(series[1]).toMatchObject({
                    key: '4__trendline',
                    label: 'Pageview',
                    color: hexToRGBA(RED, 0.5),
                    yAxisId: DEFAULT_Y_AXIS_ID,
                    stroke: { pattern: [1, 3] },
                    visibility: { fromTooltip: true, fromValueLabels: true, fromStack: true },
                })
            })

            it('uses the un-dimmed base color for the trend-line, independent of compare-previous dimming', () => {
                // Compare across both compare states. Main.color reflects compare-dimming;
                // the trend-line is derived from the un-dimmed baseColor, so it must be
                // identical in both. If the implementation regressed to dimming twice
                // (e.g. used main.color), current[1].color would diverge from previous[1].color.
                const current = buildTrendsSeries([makeResult({ compare: true, compare_label: 'current' })], tlOpts)
                const previous = buildTrendsSeries([makeResult({ compare: true, compare_label: 'previous' })], tlOpts)

                expect(current[0].color).not.toBe(previous[0].color)
                expect(current[1].color).toBe(previous[1].color)
                expect(current[1].color).toBe(hexToRGBA(RED, 0.5))
            })

            it('fits the trend-line up to dashedFromIndex (excludes the in-progress tail)', () => {
                const data = [0, 0, 0, 0, 0, 100, 100]
                // incompletenessOffsetFromEnd=-2 → dashedFromIndex=5 → fit excludes the 100s.
                const series = buildTrendsSeries([makeResult({ data })], {
                    ...tlOpts,
                    incompletenessOffsetFromEnd: -2,
                })
                const fitted = series[1].data
                // Slope is zero for the fitted prefix — every fitted value should be ~0.
                expect(fitted?.every((v) => Math.abs(v) < 1e-9)).toBe(true)
            })

            it('skips the trend-line when the main series is excluded', () => {
                const series = buildTrendsSeries([makeResult()], { ...tlOpts, getHidden: () => true })
                expect(series).toHaveLength(1)
            })

            it('skips the trend-line when showTrendLines is false', () => {
                const series = buildTrendsSeries([makeResult()], { getColor: () => RED })
                expect(series).toHaveLength(1)
            })
        })

        describe('moving-average trend line', () => {
            const maTlOpts = {
                getColor: (): string => RED,
                showMovingAverage: true,
                movingAverageIntervals: 3,
                showTrendLines: true,
            }

            it('emits an MA trend-line subseries when both MA and trendlines are enabled', () => {
                const series = buildTrendsSeries([makeResult({ id: 2 })], maTlOpts)
                expect(series).toHaveLength(4)
                expect(series.map((s) => s.key)).toEqual(['2', '2-ma', '2-ma__trendline', '2__trendline'])
            })

            it('skips the MA trend-line when the main series is excluded (but still keeps the MA itself)', () => {
                const series = buildTrendsSeries([makeResult({ id: 2 })], { ...maTlOpts, getHidden: () => true })
                expect(series.map((s) => s.key)).toEqual(['2', '2-ma'])
            })

            it('skips the MA trend-line when MA is gated out by short data', () => {
                const series = buildTrendsSeries([makeResult({ data: [1, 2] })], maTlOpts)
                expect(series.map((s) => s.key)).toEqual(['0', '0__trendline'])
            })
        })

        describe('composition', () => {
            it('emits derived series in order [main, CI, MA, MA-trendline, raw-trendline] when all are enabled', () => {
                const series = buildTrendsSeries([makeResult({ id: 'x', data: [1, 2, 3, 4, 5] })], {
                    getColor: () => RED,
                    showConfidenceIntervals: true,
                    confidenceLevel: 95,
                    showMovingAverage: true,
                    movingAverageIntervals: 3,
                    showTrendLines: true,
                })

                expect(series.map((s) => s.key)).toEqual(['x', 'x__ci', 'x-ma', 'x-ma__trendline', 'x__trendline'])
            })

            it('preserves the result iteration order across multiple results', () => {
                const series = buildTrendsSeries([makeResult({ id: 'a' }), makeResult({ id: 'b' })], {
                    getColor: () => RED,
                    showTrendLines: true,
                })
                expect(series.map((s) => s.key)).toEqual(['a', 'a__trendline', 'b', 'b__trendline'])
            })
        })
    })

    describe('buildTrendsChartConfig', () => {
        it('returns every optional key undefined and yScaleType "linear" when no opts are provided', () => {
            const config = buildTrendsChartConfig({})
            expect(config).toEqual({
                showGrid: undefined,
                showCrosshair: undefined,
                tooltip: undefined,
                yScaleType: 'linear',
                percentStackView: undefined,
                xTickFormatter: undefined,
                yTickFormatter: undefined,
            })
        })

        it.each([
            ['log10', 'log'],
            ['linear', 'linear'],
            ['auto', 'linear'],
            [undefined, 'linear'],
            [null, 'linear'],
        ] as const)('translates yAxisScaleType "%s" to hog-charts yScaleType "%s"', (input, expected) => {
            expect(buildTrendsChartConfig({ yAxisScaleType: input }).yScaleType).toBe(expected)
        })

        it('builds a tooltip object only when pinnable or placement is set', () => {
            expect(buildTrendsChartConfig({ pinnableTooltip: true, tooltipPlacement: 'top' }).tooltip).toEqual({
                pinnable: true,
                placement: 'top',
            })
            expect(buildTrendsChartConfig({}).tooltip).toBeUndefined()
        })

        it('passes through grid, crosshair, percentStackView, and tick formatters', () => {
            const xTickFormatter = (v: string | number): string | null => String(v)
            const yTickFormatter = (v: number): string => `${v}`

            expect(
                buildTrendsChartConfig({
                    showGrid: true,
                    showCrosshair: true,
                    isPercentStackView: true,
                    xTickFormatter,
                    yTickFormatter,
                })
            ).toMatchObject({
                showGrid: true,
                showCrosshair: true,
                percentStackView: true,
                xTickFormatter,
                yTickFormatter,
            })
        })
    })
})
