import { ChartDisplayType } from '~/types'

import { AxisSeries, AxisSeriesSettings } from '../../dataVisualizationLogic'
import { LineGraphProps, sqlChartComponentFor } from './LineGraph'

const baseProps = (visualizationType: ChartDisplayType): LineGraphProps => ({
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
        ['line', ChartDisplayType.ActionsLineGraph, true, 'SqlLineGraph'],
        ['bar', ChartDisplayType.ActionsBar, true, 'SqlBarGraph'],
        ['line with the flag off', ChartDisplayType.ActionsLineGraph, false, 'LegacyLineGraph'],
        // Pie is not routed here — it has its own wrapper (see PieChart.test.tsx).
        ['pie (handled by the PieChart wrapper, not here)', ChartDisplayType.ActionsPie, true, 'SqlLineGraph'],
    ])('routes %s to the right component', (_name, visualizationType, newChartsEnabled, expected) => {
        expect(sqlChartComponentFor(baseProps(visualizationType), newChartsEnabled).name).toBe(expected)
    })

    it.each([
        ['a bar-base chart', ChartDisplayType.ActionsBar],
        ['a line-base chart', ChartDisplayType.ActionsLineGraph],
    ])('routes mixed bar + line series on %s to SqlComboGraph', (_name, visualizationType) => {
        expect(sqlChartComponentFor({ ...baseProps(visualizationType), yData: mixedYData }, true).name).toBe(
            'SqlComboGraph'
        )
    })

    it('keeps mixed series on the legacy path when the flag is off', () => {
        expect(sqlChartComponentFor({ ...baseProps(ChartDisplayType.ActionsBar), yData: mixedYData }, false).name).toBe(
            'LegacyLineGraph'
        )
    })
})
