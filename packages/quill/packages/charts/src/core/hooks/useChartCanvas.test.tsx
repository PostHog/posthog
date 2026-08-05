import { act } from '@testing-library/react'

import { mockRect, renderHogChart } from '../../testing'
import { Chart } from '../Chart'
import type { ChartDrawArgs, ChartScales, ChartTheme, Series } from '../types'

const THEME: ChartTheme = { colors: ['#f00'], gridColor: '#eee', crosshairColor: '#888' }

const SERIES: Series[] = [{ key: 'a', label: 'A', data: [10, 20, 30] }]

const LABELS = ['Mon', 'Tue', 'Wed']

const createScales = (): ChartScales => ({
    x: () => 100,
    y: (value: number) => 200 - value,
    yTicks: () => [0, 50, 100],
})

function renderChart(drawStatic: (args: ChartDrawArgs) => void): HTMLCanvasElement {
    const { chart } = renderHogChart(
        <Chart
            series={SERIES}
            labels={LABELS}
            theme={THEME}
            createScales={createScales}
            drawStatic={drawStatic}
            drawHover={() => false}
        />
    )
    return chart.canvas
}

describe('useChartCanvas', () => {
    afterEach(() => {
        Object.defineProperty(document, 'hidden', { value: false, configurable: true })
    })

    it('repaints against a restored backing store after the 2D context is lost', () => {
        const drawStatic = jest.fn()
        const canvas = renderChart(drawStatic)
        expect(drawStatic).toHaveBeenCalled()

        drawStatic.mockClear()
        act(() => {
            canvas.dispatchEvent(new Event('contextrestored'))
        })

        expect(drawStatic).toHaveBeenCalled()
        expect(canvas.width).toBe(mockRect.width)
    })

    it('repaints on resume from a background tab even without a contextrestored event', () => {
        const drawStatic = jest.fn()
        const canvas = renderChart(drawStatic)
        expect(drawStatic).toHaveBeenCalled()

        // Simulate the backing store being reclaimed while idle: the bitmap is wiped but the
        // wrapper's geometry hasn't changed, so ResizeObserver never fires on its own.
        canvas.width = 0
        drawStatic.mockClear()

        Object.defineProperty(document, 'hidden', { value: true, configurable: true })
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })
        expect(drawStatic).not.toHaveBeenCalled()

        Object.defineProperty(document, 'hidden', { value: false, configurable: true })
        act(() => {
            document.dispatchEvent(new Event('visibilitychange'))
        })

        expect(drawStatic).toHaveBeenCalled()
        expect(canvas.width).toBe(mockRect.width)
    })
})
