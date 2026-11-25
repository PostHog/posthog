import { ChartDisplayType } from '~/types'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { SqlChart, SqlChartProps, isSqlChartVisualizationType, sqlChartComponentFor } from './SqlChart'

const baseProps = (visualizationType: ChartDisplayType): SqlChartProps => ({
    xData: null,
    yData: [],
    visualizationType,
    chartSettings: {},
})

const ySeries = (name: string, settings: AxisSeriesSettings): AxisSeries<number | null> => ({
    column: { name, type: { name: 'INTEGER', isNumerical: true }, label: name, dataIndex: 1 },
    data: [1],
    settings,
})

// A line + bar mix routes neither to the line-only nor the bar-only path.
const mixedYData: AxisSeries<number | null>[] = [
    ySeries('a', { display: { displayType: 'line' } }),
    ySeries('b', { display: { displayType: 'bar' } }),
]

describe('sqlChartComponentFor', () => {
    it.each([
        ChartDisplayType.ActionsLineGraph,
        ChartDisplayType.ActionsBar,
        ChartDisplayType.ActionsBarValue,
        ChartDisplayType.ActionsAreaGraph,
        ChartDisplayType.ActionsStackedBar,
    ])('routes %s through SqlChart', (visualizationType) => {
        expect(isSqlChartVisualizationType(visualizationType)).toBe(true)
    })

    it.each([
        ['line', ChartDisplayType.ActionsLineGraph, 'SqlLineGraph'],
        ['bar', ChartDisplayType.ActionsBar, 'SqlBarGraph'],
        ['horizontal bar', ChartDisplayType.ActionsBarValue, 'SqlBarGraph'],
        // Pie is not routed here — it has its own wrapper (see PieChart.test.tsx).
        ['pie (handled by PartOfWholeChart, not here)', ChartDisplayType.ActionsPie, 'SqlLineGraph'],
    ])('routes %s to the right component', (_name, visualizationType, expected) => {
        expect(sqlChartComponentFor(baseProps(visualizationType)).name).toBe(expected)
    })

    it.each([
        ['a bar-base chart', ChartDisplayType.ActionsBar],
        ['a line-base chart', ChartDisplayType.ActionsLineGraph],
    ])('routes mixed bar + line series on %s to SqlComboGraph', (_name, visualizationType) => {
        expect(sqlChartComponentFor({ ...baseProps(visualizationType), yData: mixedYData }).name).toBe('SqlComboGraph')
    })

    it('keeps horizontal bars when a series has a saved line display type', () => {
        const lineSeries = [ySeries('a', { display: { displayType: 'line' } })]
        expect(sqlChartComponentFor({ ...baseProps(ChartDisplayType.ActionsBarValue), yData: lineSeries }).name).toBe(
            'SqlBarGraph'
        )
    })

    it('routes an all-bar line chart to SqlBarGraph', () => {
        const allBars = [
            ySeries('a', { display: { displayType: 'bar' } }),
            ySeries('b', { display: { displayType: 'bar' } }),
        ]
        expect(sqlChartComponentFor({ ...baseProps(ChartDisplayType.ActionsLineGraph), yData: allBars }).name).toBe(
            'SqlBarGraph'
        )
    })

    it("routes a percent stack whose line shares the bars' axis to SqlBarGraph", () => {
        expect(
            sqlChartComponentFor({
                ...baseProps(ChartDisplayType.ActionsStackedBar),
                yData: mixedYData,
                chartSettings: { stackBars100: true },
            }).name
        ).toBe('SqlBarGraph')
    })
})

it('filters by the raw clicked event when two points have the same displayed label', () => {
    const filter = jest.fn()
    const chart = SqlChart({
        ...baseProps(ChartDisplayType.ActionsLineGraph),
        xData: {
            column: { name: 'event', label: 'event', type: { name: 'STRING', isNumerical: false }, dataIndex: 0 },
            data: ['Pageview', 'Pageview'],
            rawData: ['$pageview', 'Pageview'],
        },
        chartInputFilters: { event: filter },
    })
    chart.props.onPointClick('events', 0, 'Pageview')
    chart.props.onPointClick('events', 1, 'Pageview')
    expect(filter.mock.calls).toEqual([['$pageview'], ['Pageview']])
})
