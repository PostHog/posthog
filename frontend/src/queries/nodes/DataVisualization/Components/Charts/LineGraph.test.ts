import { ChartDisplayType } from '~/types'

import { LineGraphProps, sqlChartComponentFor } from './LineGraph'

const baseProps = (visualizationType: ChartDisplayType): LineGraphProps => ({
    xData: null,
    yData: [],
    visualizationType,
    chartSettings: {},
})

describe('sqlChartComponentFor', () => {
    it.each([
        ['line', ChartDisplayType.ActionsLineGraph, true, 'SqlLineGraph'],
        ['bar', ChartDisplayType.ActionsBar, true, 'SqlBarGraph'],
        ['line with the flag off', ChartDisplayType.ActionsLineGraph, false, 'LegacyLineGraph'],
        ['an unsupported visualization', ChartDisplayType.ActionsPie, true, 'LegacyLineGraph'],
    ])('routes %s to the right component', (_name, visualizationType, newChartsEnabled, expected) => {
        expect(sqlChartComponentFor(baseProps(visualizationType), newChartsEnabled).name).toBe(expected)
    })
})
