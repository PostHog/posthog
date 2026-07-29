import { ChartDisplayType } from '~/types'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { SqlChartProps, sqlChartComponentFor } from './SqlChart'

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
        ['line', ChartDisplayType.ActionsLineGraph, 'SqlLineGraph'],
        ['bar', ChartDisplayType.ActionsBar, 'SqlBarGraph'],
        // Pie is not routed here — it has its own wrapper (see PieChart.test.tsx).
        ['pie (handled by the PieChart wrapper, not here)', ChartDisplayType.ActionsPie, 'SqlLineGraph'],
    ])('routes %s to the right component', (_name, visualizationType, expected) => {
        expect(sqlChartComponentFor(baseProps(visualizationType)).name).toBe(expected)
    })

    it.each([
        ['a bar-base chart', ChartDisplayType.ActionsBar],
        ['a line-base chart', ChartDisplayType.ActionsLineGraph],
    ])('routes mixed bar + line series on %s to SqlComboGraph', (_name, visualizationType) => {
        expect(sqlChartComponentFor({ ...baseProps(visualizationType), yData: mixedYData }).name).toBe('SqlComboGraph')
    })
})
