import { type TooltipContext } from '@posthog/quill-charts'

import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'
import {
    AREA_FILL_OPACITY,
    MAX_SERIES,
    type SqlLineSeriesMeta,
    buildLineChartConfig,
    buildSeries,
    buildSqlLineTooltipModel,
    canRenderSqlLineGraph,
    capYSeriesData,
    exceedsMaxSeries,
} from './sqlLineGraphAdapter'

const numericColumn = (name: string, dataIndex: number): AxisSeries<number | null>['column'] => ({
    name,
    type: { name: 'INTEGER', isNumerical: true },
    label: name,
    dataIndex,
})

const ySeries = (
    name: string,
    data: (number | null)[],
    settings: AxisSeries<number | null>['settings'] = {}
): AxisSeries<number | null> => ({ column: numericColumn(name, 1), data, settings })

const breakdownSeries = (
    breakdownValue: string,
    data: (number | null)[],
    settings: AxisBreakdownSeries<number | null>['settings'] = {}
): AxisBreakdownSeries<number | null> => ({ name: breakdownValue, breakdownValue, data, settings })

const baseProps = (overrides: Partial<LineGraphProps>): LineGraphProps => ({
    xData: null,
    yData: [],
    visualizationType: ChartDisplayType.ActionsLineGraph,
    chartSettings: {},
    ...overrides,
})

describe('sqlLineGraphAdapter', () => {
    describe('canRenderSqlLineGraph', () => {
        it.each([
            ['line graph', ChartDisplayType.ActionsLineGraph, true],
            ['area graph', ChartDisplayType.ActionsAreaGraph, true],
            ['bar graph', ChartDisplayType.ActionsBar, false],
            ['stacked bar graph', ChartDisplayType.ActionsStackedBar, false],
        ])('returns %s support correctly for %s', (_name, visualizationType, expected) => {
            expect(canRenderSqlLineGraph(baseProps({ visualizationType }))).toBe(expected)
        })

        it('falls back when any series renders as a bar', () => {
            const yData = [ySeries('a', [1]), ySeries('b', [2], { display: { displayType: 'bar' } })]
            expect(canRenderSqlLineGraph(baseProps({ yData }))).toBe(false)
        })

        it('falls back when any series has a trend line', () => {
            const yData = [ySeries('a', [1], { display: { trendLine: true } })]
            expect(canRenderSqlLineGraph(baseProps({ yData }))).toBe(false)
        })

        it('falls back when any series targets the right y-axis', () => {
            const yData = [ySeries('a', [1], { display: { yAxisPosition: 'right' } })]
            expect(canRenderSqlLineGraph(baseProps({ yData }))).toBe(false)
        })
    })

    describe('exceedsMaxSeries', () => {
        const tooMany = Array.from({ length: MAX_SERIES + 1 }, (_, i) => ySeries(`s${i}`, [i]))

        it('is true above the cap outside a dashboard', () => {
            expect(exceedsMaxSeries(tooMany, undefined)).toBe(true)
        })

        it('is false above the cap on a dashboard', () => {
            expect(exceedsMaxSeries(tooMany, 'dash-1')).toBe(false)
        })

        it('is false at or below the cap', () => {
            expect(exceedsMaxSeries([ySeries('a', [1])], undefined)).toBe(false)
        })
    })

    describe('capYSeriesData', () => {
        it('returns null for missing data', () => {
            expect(capYSeriesData(undefined as unknown as LineGraphProps['yData'])).toBeNull()
        })

        it('returns the data unchanged at or below the cap', () => {
            const yData = [ySeries('a', [1]), ySeries('b', [2])]
            expect(capYSeriesData(yData)).toBe(yData)
        })

        it('slices to the cap when exceeded', () => {
            const yData = Array.from({ length: MAX_SERIES + 5 }, (_, i) => ySeries(`s${i}`, [i]))
            expect(capYSeriesData(yData)).toHaveLength(MAX_SERIES)
        })
    })

    describe('buildSeries', () => {
        it('maps nulls to NaN so quill draws gaps', () => {
            const [series] = buildSeries([ySeries('a', [1, null, 3])], ChartDisplayType.ActionsLineGraph)
            expect(series.data).toEqual([1, NaN, 3])
        })

        it('only pins an explicit color, leaving palette assignment to quill otherwise', () => {
            const [withColor, withoutColor] = buildSeries(
                [ySeries('a', [1], { display: { color: '#abcdef' } }), ySeries('b', [2])],
                ChartDisplayType.ActionsLineGraph
            )
            expect(withColor.color).toBe('#abcdef')
            expect(withoutColor.color).toBeUndefined()
        })

        it('adds an area fill for area graphs', () => {
            const [series] = buildSeries([ySeries('a', [1])], ChartDisplayType.ActionsAreaGraph)
            expect(series.fill).toEqual({ opacity: AREA_FILL_OPACITY })
        })

        it('adds an area fill when a series opts into area display', () => {
            const [series] = buildSeries(
                [ySeries('a', [1], { display: { displayType: 'area' } })],
                ChartDisplayType.ActionsLineGraph
            )
            expect(series.fill).toEqual({ opacity: AREA_FILL_OPACITY })
        })

        it('omits the fill for plain line graphs', () => {
            const [series] = buildSeries([ySeries('a', [1])], ChartDisplayType.ActionsLineGraph)
            expect(series.fill).toBeUndefined()
        })

        it('keys breakdown series by breakdown value', () => {
            const [series] = buildSeries([breakdownSeries('chrome', [1])], ChartDisplayType.ActionsLineGraph)
            expect(series.key).toBe('chrome')
        })
    })

    describe('buildSqlLineTooltipModel', () => {
        type TooltipEntry = { key: string; label: string; value: number; color: string; settings?: AxisSeriesSettings }

        const tooltipContext = (entries: TooltipEntry[], label = '2024-01-01'): TooltipContext<SqlLineSeriesMeta> =>
            ({
                dataIndex: 0,
                label,
                seriesData: entries.map(({ key, label: seriesLabel, value, color, settings }) => ({
                    series: { key, label: seriesLabel, data: [value], meta: { settings } },
                    value,
                    color,
                })),
                position: { x: 0, y: 0 },
                hoverPosition: null,
                canvasBounds: {} as DOMRect,
                isPinned: false,
            }) as TooltipContext<SqlLineSeriesMeta>

        it('passes the x-axis label through', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([{ key: 'a', label: 'A', value: 1, color: '#111' }]),
                {}
            )
            expect(model.label).toBe('2024-01-01')
        })

        it('formats values per series settings and carries the row color', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    { key: 'a', label: 'A', value: 1234, color: '#abc', settings: { formatting: { style: 'number' } } },
                ]),
                {}
            )
            expect(model.rows).toEqual([{ key: 'a', name: 'A', color: '#abc', value: '1,234', rawValue: 1234 }])
        })

        it('sorts rows by value descending', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    { key: 'a', label: 'A', value: 1, color: '#111' },
                    { key: 'b', label: 'B', value: 9, color: '#222' },
                    { key: 'c', label: 'C', value: 5, color: '#333' },
                ]),
                {}
            )
            expect(model.rows.map((r) => r.key)).toEqual(['b', 'c', 'a'])
        })

        it('drops empty (NaN) points', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    { key: 'a', label: 'A', value: NaN, color: '#111' },
                    { key: 'b', label: 'B', value: 2, color: '#222' },
                ]),
                {}
            )
            expect(model.rows.map((r) => r.key)).toEqual(['b'])
        })

        it('prefers an explicit display label over the series label', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    {
                        key: 'a',
                        label: 'raw name',
                        value: 1,
                        color: '#111',
                        settings: { display: { label: 'Pretty' } },
                    },
                ]),
                {}
            )
            expect(model.rows[0].name).toBe('Pretty')
        })

        it('adds a total row summing non-percent series', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    { key: 'a', label: 'A', value: 2, color: '#111' },
                    { key: 'b', label: 'B', value: 3, color: '#222' },
                ]),
                {}
            )
            expect(model.totalLabel).toBe('5')
        })

        it('excludes percent-formatted series from the total', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    { key: 'a', label: 'A', value: 2, color: '#111' },
                    { key: 'b', label: 'B', value: 3, color: '#222' },
                    { key: 'c', label: 'C', value: 50, color: '#333', settings: { formatting: { style: 'percent' } } },
                ]),
                {}
            )
            expect(model.totalLabel).toBe('5')
        })

        it('omits the total row for a single series', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([{ key: 'a', label: 'A', value: 2, color: '#111' }]),
                {}
            )
            expect(model.totalLabel).toBeNull()
        })

        it('omits the total row when showTotalRow is disabled', () => {
            const model = buildSqlLineTooltipModel(
                tooltipContext([
                    { key: 'a', label: 'A', value: 2, color: '#111' },
                    { key: 'b', label: 'B', value: 3, color: '#222' },
                ]),
                { showTotalRow: false }
            )
            expect(model.totalLabel).toBeNull()
        })
    })

    describe('buildSeries meta', () => {
        it('threads per-series settings into meta for the tooltip', () => {
            const settings: AxisSeriesSettings = { formatting: { style: 'number' } }
            const [series] = buildSeries([ySeries('a', [1], settings)], ChartDisplayType.ActionsLineGraph)
            expect(series.meta).toEqual({ settings })
        })
    })

    describe('buildLineChartConfig', () => {
        const dateXData: AxisSeries<string> = {
            column: { name: 'day', type: { name: 'DATE', isNumerical: false }, label: 'day', dataIndex: 0 },
            data: ['2024-01-01', '2024-01-02'],
        }
        const stringXData: AxisSeries<string> = {
            column: { name: 'name', type: { name: 'STRING', isNumerical: false }, label: 'name', dataIndex: 0 },
            data: ['a', 'b'],
        }

        it('adds an x-axis tick formatter for date axes', () => {
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC' })
            expect(config.xAxis?.tickFormatter).toBeInstanceOf(Function)
        })

        it('omits the tick formatter for non-date axes', () => {
            const config = buildLineChartConfig({ xData: stringXData, chartSettings: {}, timezone: 'UTC' })
            expect(config.xAxis?.tickFormatter).toBeUndefined()
        })

        it('maps logarithmic scale and y-axis settings', () => {
            const chartSettings: ChartSettings = {
                leftYAxisSettings: { label: 'Count', scale: 'logarithmic', showGridLines: false, showTicks: false },
            }
            const config = buildLineChartConfig({ xData: dateXData, chartSettings, timezone: 'UTC' })
            expect(config.yAxis).toMatchObject({ label: 'Count', scale: 'log', showGrid: false, hide: true })
        })

        it('defaults to a linear scale with grid shown', () => {
            const config = buildLineChartConfig({ xData: dateXData, chartSettings: {}, timezone: 'UTC' })
            expect(config.yAxis).toMatchObject({ scale: 'linear', showGrid: true })
        })
    })
})
