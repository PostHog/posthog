import { DEFAULT_Y_AXIS_ID } from 'lib/hog-charts'
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
        it('assigns yAxisIds [left, y1, y2] across three results when showMultipleYAxes is true', () => {
            const results = [makeResult({ id: 'a' }), makeResult({ id: 'b' }), makeResult({ id: 'c' })]
            const built = buildTrendsSeries(results, { getColor: () => RED, showMultipleYAxes: true })

            expect(built.map((b) => b.main.yAxisId)).toEqual([DEFAULT_Y_AXIS_ID, 'y1', 'y2'])
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
