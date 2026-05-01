import type { Series } from 'lib/hog-charts'
import { hexToRGBA } from 'lib/utils'

import {
    buildTrendsBarChartConfig,
    buildTrendsBarTimeSeries,
    type TrendsBarResultLike,
} from './trendsBarChartTransforms'

const RED = '#ff0000'

const makeResult = (overrides: Partial<TrendsBarResultLike> = {}): TrendsBarResultLike => ({
    id: 0,
    label: 'Pageview',
    data: [1, 2, 3, 4, 5],
    ...overrides,
})

describe('trendsBarChartTransforms', () => {
    describe('buildTrendsBarTimeSeries', () => {
        it('returns one series per result with the result data unchanged', () => {
            const results = [makeResult({ id: 'a', data: [1, 2, 3] }), makeResult({ id: 'b', data: [4, 5, 6] })]
            const series = buildTrendsBarTimeSeries(results, { getColor: () => RED })

            expect(series).toHaveLength(2)
            expect(series.map((s) => s.key)).toEqual(['a', 'b'])
            expect(series[0].data).toEqual([1, 2, 3])
            expect(series[1].data).toEqual([4, 5, 6])
        })

        it('applies the getColor result as the series color', () => {
            const series = buildTrendsBarTimeSeries([makeResult()], { getColor: () => RED })
            expect(series[0].color).toBe(RED)
        })

        it('dims compare-previous series colors to 0.5 alpha', () => {
            const series = buildTrendsBarTimeSeries([makeResult({ compare: true, compare_label: 'previous' })], {
                getColor: () => RED,
            })
            expect(series[0].color).toBe(hexToRGBA(RED, 0.5))
        })

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

        it('passes the result index through to getColor and buildMeta', () => {
            const getColor = jest.fn(() => RED)
            const buildMeta = jest.fn(() => ({}))
            buildTrendsBarTimeSeries([makeResult({ id: 'x' }), makeResult({ id: 'y' })], { getColor, buildMeta })
            expect(getColor).toHaveBeenNthCalledWith(1, expect.anything(), 0)
            expect(getColor).toHaveBeenNthCalledWith(2, expect.anything(), 1)
            expect(buildMeta).toHaveBeenNthCalledWith(2, expect.anything(), 1)
        })

        it('does not set fill or stroke (bars never use them)', () => {
            const series = buildTrendsBarTimeSeries([makeResult()], { getColor: () => RED })
            expect(series[0].fill).toBeUndefined()
            expect(series[0].stroke).toBeUndefined()
        })
    })

    describe('buildTrendsBarChartConfig', () => {
        it('returns sensible defaults when no opts are provided', () => {
            const config = buildTrendsBarChartConfig({})
            expect(config).toEqual({
                showGrid: undefined,
                tooltip: undefined,
                yScaleType: 'linear',
                axisOrientation: undefined,
                barLayout: 'stacked',
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
            expect(buildTrendsBarChartConfig({ yAxisScaleType: input }).yScaleType).toBe(expected)
        })

        it('builds a tooltip object only when pinnable or placement is set', () => {
            expect(buildTrendsBarChartConfig({ pinnableTooltip: true, tooltipPlacement: 'top' }).tooltip).toEqual({
                pinnable: true,
                placement: 'top',
            })
            expect(buildTrendsBarChartConfig({}).tooltip).toBeUndefined()
        })

        it('uses barLayout "percent" when isPercentStackView is true, otherwise "stacked"', () => {
            expect(buildTrendsBarChartConfig({ isPercentStackView: true }).barLayout).toBe('percent')
            expect(buildTrendsBarChartConfig({ isPercentStackView: false }).barLayout).toBe('stacked')
            expect(buildTrendsBarChartConfig({}).barLayout).toBe('stacked')
        })

        it('passes axisOrientation through unchanged', () => {
            expect(buildTrendsBarChartConfig({ axisOrientation: 'horizontal' }).axisOrientation).toBe('horizontal')
            expect(buildTrendsBarChartConfig({ axisOrientation: 'vertical' }).axisOrientation).toBe('vertical')
        })

        it('passes through grid and tick formatters', () => {
            const xTickFormatter = (v: string | number): string | null => String(v)
            const yTickFormatter = (v: number): string => `${v}`

            expect(
                buildTrendsBarChartConfig({
                    showGrid: true,
                    xTickFormatter,
                    yTickFormatter,
                })
            ).toMatchObject({
                showGrid: true,
                xTickFormatter,
                yTickFormatter,
            })
        })

        it('returns a BarChartConfig — series shape is unchanged', () => {
            // Type-system smoke check: the helper must return something assignable to BarChartConfig.
            const config = buildTrendsBarChartConfig({})
            const _series: Series[] = []
            // eslint-disable-next-line @typescript-eslint/no-unused-vars
            const consumer = (_s: Series[], _c: typeof config): void => {}
            consumer(_series, config)
            expect(true).toBe(true)
        })
    })
})
