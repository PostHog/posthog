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

let resizeObserverCallback: ResizeObserverCallback = () => {}

function reportWrapperSize(width: number, height: number): void {
    const entry = { borderBoxSize: [{ inlineSize: width, blockSize: height }] } as unknown as ResizeObserverEntry
    act(() => resizeObserverCallback([entry], {} as ResizeObserver))
}

describe('useChartCanvas', () => {
    let resizeObserverSpy: jest.SpyInstance

    beforeEach(() => {
        resizeObserverSpy = jest.spyOn(globalThis, 'ResizeObserver').mockImplementation((callback) => {
            resizeObserverCallback = callback
            return { observe: () => {}, unobserve: () => {}, disconnect: () => {} }
        })
    })

    afterEach(() => {
        resizeObserverSpy.mockRestore()
    })

    it('keeps the painted canvas when the wrapper collapses to zero size and comes back', () => {
        const drawStatic = jest.fn()
        const canvas = renderChart(drawStatic)
        drawStatic.mockClear()

        reportWrapperSize(0, 0)
        expect(canvas.width).toBe(mockRect.width)

        reportWrapperSize(mockRect.width, mockRect.height)
        expect(drawStatic).not.toHaveBeenCalled()
    })

    it('repaints a context restored while the wrapper had zero size once the size comes back', () => {
        const drawStatic = jest.fn()
        const canvas = renderChart(drawStatic)
        drawStatic.mockClear()

        jest.mocked(Element.prototype.getBoundingClientRect).mockReturnValueOnce({ ...mockRect, width: 0, height: 0 })
        act(() => {
            canvas.dispatchEvent(new Event('contextrestored'))
        })
        expect(drawStatic).not.toHaveBeenCalled()

        reportWrapperSize(mockRect.width, mockRect.height)
        expect(drawStatic).toHaveBeenCalled()
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
})
