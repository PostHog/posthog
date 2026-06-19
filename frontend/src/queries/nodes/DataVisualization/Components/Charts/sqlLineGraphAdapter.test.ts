import { ChartSettings } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { AxisSeries } from '../../dataVisualizationLogic'
import { AxisBreakdownSeries } from '../seriesBreakdownLogic'
import { LineGraphProps } from './LineGraph'
import {
    AREA_FILL_OPACITY,
    MAX_SERIES,
    buildLineChartConfig,
    buildSeries,
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
