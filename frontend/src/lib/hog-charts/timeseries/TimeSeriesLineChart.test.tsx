import { render } from '@testing-library/react'

import type { LineChartProps } from '../charts/LineChart'
import type { ChartTheme, Series } from '../core/types'

const lineChartSpy = jest.fn()

jest.mock('../charts/LineChart', () => ({
    LineChart: (props: LineChartProps) => {
        lineChartSpy(props)
        return <div data-attr="line-chart-mock" />
    },
}))

import { TimeSeriesLineChart } from './TimeSeriesLineChart'

const THEME: ChartTheme = { colors: ['#111', '#222', '#333'], backgroundColor: '#ffffff' }
const LABELS = ['Mon', 'Tue', 'Wed']
const SERIES: Series[] = [{ key: 'a', label: 'A', data: [1, 2, 3] }]

describe('TimeSeriesLineChart', () => {
    it('translates config.xAxis and config.yAxis fields onto LineChartConfig', () => {
        const xTickFormatter = (v: string): string => `x:${v}`
        const yTickFormatter = (v: number): string => `y:${v}`
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{
                    xAxis: { tickFormatter: xTickFormatter, hide: true },
                    yAxis: { scale: 'log', tickFormatter: yTickFormatter, hide: true, showGrid: true },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.labels).toBe(LABELS)
        expect(props.config?.yScaleType).toBe('log')
        expect(props.config?.xTickFormatter).toBe(xTickFormatter)
        expect(props.config?.yTickFormatter).toBe(yTickFormatter)
        expect(props.config?.hideXAxis).toBe(true)
        expect(props.config?.hideYAxis).toBe(true)
        expect(props.config?.showGrid).toBe(true)
    })
})
