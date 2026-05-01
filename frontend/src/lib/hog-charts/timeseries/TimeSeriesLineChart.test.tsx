import { cleanup, render } from '@testing-library/react'

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
    afterEach(() => cleanup())

    it('renders without crashing', () => {
        const { getByTestId } = render(<TimeSeriesLineChart series={SERIES} xAxis={{ labels: LABELS }} theme={THEME} />)
        expect(getByTestId('line-chart-mock')).toBeTruthy()
    })

    it('passes series and labels through to the underlying LineChart', () => {
        const series: Series[] = [
            { key: 'a', label: 'A', data: [1, 2, 3] },
            { key: 'b', label: 'B', data: [4, 5, 6] },
        ]
        render(
            <TimeSeriesLineChart
                series={series}
                xAxis={{ labels: LABELS }}
                yAxis={{ scale: 'log', showGrid: true }}
                theme={THEME}
            />
        )
        expect(lineChartSpy).toHaveBeenCalledTimes(1)
        const props = lineChartSpy.mock.calls[0][0] as LineChartProps
        expect(props.series).toBe(series)
        expect(props.labels).toBe(LABELS)
        expect(props.theme).toBe(THEME)
        expect(props.config?.yScaleType).toBe('log')
        expect(props.config?.showGrid).toBe(true)
    })

    it.each<[string, number | string, number | string]>([
        ['numeric pixels', 640, 320],
        ['percentage / px mix', '75%', 200],
    ])('respects width/height (%s)', (_name, width, height) => {
        const { container } = render(
            <TimeSeriesLineChart
                series={SERIES}
                xAxis={{ labels: LABELS }}
                theme={THEME}
                width={width}
                height={height}
            />
        )
        const wrapper = container.firstElementChild as HTMLDivElement
        const expectedWidth = typeof width === 'number' ? `${width}px` : width
        const expectedHeight = typeof height === 'number' ? `${height}px` : height
        expect(wrapper.style.width).toBe(expectedWidth)
        expect(wrapper.style.height).toBe(expectedHeight)
    })
})
