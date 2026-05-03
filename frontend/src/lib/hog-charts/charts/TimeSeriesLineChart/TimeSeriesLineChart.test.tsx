import { render } from '@testing-library/react'

import type { ChartTheme, Series } from '../../core/types'
import type { LineChartProps } from '../LineChart'

const lineChartSpy = jest.fn()

jest.mock('../LineChart', () => ({
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
    beforeEach(() => {
        lineChartSpy.mockClear()
    })

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

    it('builds an x-axis tick formatter from xAxis.timezone + xAxis.interval', () => {
        const allDays = ['2025-04-01 14:00:00', '2025-04-01 15:00:00', '2025-04-01 16:00:00']
        render(
            <TimeSeriesLineChart
                series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                labels={['14:00', '15:00', '16:00']}
                theme={THEME}
                config={{
                    xAxis: { timezone: 'UTC', interval: 'hour', allDays },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        const formatter = props.config?.xTickFormatter
        expect(formatter).not.toBeUndefined()
        expect(formatter?.('ignored', 0)).toBe('14:00')
        expect(formatter?.('ignored', 1)).toBe('15:00')
        expect(formatter?.('ignored', 2)).toBe('16:00')
    })

    it('explicit tickFormatter wins over xAxis.timezone + xAxis.interval', () => {
        const explicit = (_v: string, i: number): string => `tick-${i}`
        render(
            <TimeSeriesLineChart
                series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                labels={['14:00', '15:00', '16:00']}
                theme={THEME}
                config={{
                    xAxis: {
                        tickFormatter: explicit,
                        timezone: 'UTC',
                        interval: 'hour',
                        allDays: ['2025-04-01 14:00:00', '2025-04-01 15:00:00', '2025-04-01 16:00:00'],
                    },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.xTickFormatter).toBe(explicit)
    })

    it('builds a y-axis tick formatter from yAxis.format', () => {
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ yAxis: { format: 'percentage' } }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        const formatter = props.config?.yTickFormatter
        expect(formatter).not.toBeUndefined()
        expect(formatter?.(50)).toBe('50%')
    })

    it('builds a y-axis tick formatter from yAxis.prefix/suffix without format', () => {
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ yAxis: { prefix: '$', suffix: ' req' } }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.yTickFormatter?.(42)).toBe('$42 req')
    })

    it('explicit yAxis.tickFormatter wins over yAxis.format', () => {
        const explicit = (v: number): string => `y:${v}`
        render(
            <TimeSeriesLineChart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                config={{ yAxis: { tickFormatter: explicit, format: 'percentage' } }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.yTickFormatter).toBe(explicit)
    })

    it('does not build a y-axis tick formatter when no format options are set', () => {
        render(<TimeSeriesLineChart series={SERIES} labels={LABELS} theme={THEME} config={{ yAxis: {} }} />)
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.yTickFormatter).toBeUndefined()
    })

    it('does not auto-format when only one of timezone or interval is provided', () => {
        render(
            <TimeSeriesLineChart
                series={[{ key: 'a', label: 'A', data: [1, 2, 3] }]}
                labels={LABELS}
                theme={THEME}
                config={{
                    xAxis: { timezone: 'UTC' },
                }}
            />
        )
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.config?.xTickFormatter).toBeUndefined()
    })
})
