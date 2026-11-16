import { act, fireEvent } from '@testing-library/react'

import { mockRect, renderChart } from '../../testing'
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

function renderCanvas(drawStatic: (args: ChartDrawArgs) => void): HTMLCanvasElement {
    const { chart } = renderChart(
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

    it('keeps the last frame until the repaint resizes the backing store', () => {
        const drawStatic = jest.fn()
        const canvas = renderCanvas(drawStatic)
        const frames: FrameRequestCallback[] = []
        const rafSpy = jest.spyOn(globalThis, 'requestAnimationFrame').mockImplementation((cb) => frames.push(cb))
        drawStatic.mockClear()

        try {
            reportWrapperSize(640, 300)
            expect(canvas.width).toBe(mockRect.width)
            expect(drawStatic).not.toHaveBeenCalled()

            act(() => frames.forEach((frame) => frame(0)))
            expect(canvas.width).toBe(640)
            expect(canvas.height).toBe(300)
            expect(drawStatic).toHaveBeenCalled()
        } finally {
            rafSpy.mockRestore()
        }
    })

    it('keeps the painted canvas when the wrapper collapses to zero size and comes back', () => {
        const drawStatic = jest.fn()
        const canvas = renderCanvas(drawStatic)
        drawStatic.mockClear()

        reportWrapperSize(0, 0)
        expect(canvas.width).toBe(mockRect.width)

        reportWrapperSize(mockRect.width, mockRect.height)
        expect(drawStatic).not.toHaveBeenCalled()
    })

    it('repaints a context restored while the wrapper had zero size once the size comes back', () => {
        const drawStatic = jest.fn()
        const canvas = renderCanvas(drawStatic)
        drawStatic.mockClear()

        jest.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValueOnce({ ...mockRect, width: 0, height: 0 })
        act(() => {
            canvas.dispatchEvent(new Event('contextrestored'))
        })
        expect(drawStatic).not.toHaveBeenCalled()

        reportWrapperSize(mockRect.width, mockRect.height)
        expect(drawStatic).toHaveBeenCalled()
    })

    it('holds a hover overlay bitmap only while the chart is hovered', () => {
        const { chart } = renderChart(
            <Chart
                series={SERIES}
                labels={LABELS}
                theme={THEME}
                createScales={createScales}
                drawStatic={() => {}}
                drawHover={() => true}
            />
        )
        const overlay = chart.element.querySelector<HTMLCanvasElement>('canvas[aria-hidden="true"]')!
        expect([overlay.width, overlay.height]).toEqual([0, 0])

        chart.hoverAtIndex(1)
        expect([overlay.width, overlay.height]).toEqual([mockRect.width, mockRect.height])

        act(() => {
            fireEvent.mouseLeave(chart.element)
        })
        expect([overlay.width, overlay.height]).toEqual([0, 0])
    })

    // A move to a screen with another pixel ratio fires the same `visualViewport` resize as a pinch-zoom.
    it.each([
        ['repaints an on-screen chart at the pinch-zoom scale', true, 2, 1, mockRect.width * 2, 1],
        ['skips the repaint for an off-screen chart under pinch-zoom', false, 2, 1, mockRect.width, 0],
        ['repaints an off-screen chart at the new pixel ratio after a screen move', false, 1, 2, mockRect.width * 2, 1],
    ])('%s once the viewport settles', (_, onScreen, zoom, dpr, expectedWidth, repaints) => {
        const originalDpr = window.devicePixelRatio
        let onViewportResize = (): void => {}
        let onVisibilityChange: IntersectionObserverCallback = () => {}
        const viewport = {
            scale: 1,
            addEventListener: (_event: string, listener: () => void) => {
                onViewportResize = listener
            },
            removeEventListener: () => {},
        }
        Object.defineProperty(window, 'visualViewport', { value: viewport, configurable: true })
        const originalIntersectionObserver = globalThis.IntersectionObserver
        globalThis.IntersectionObserver = jest.fn((callback: IntersectionObserverCallback) => {
            onVisibilityChange = callback
            return { observe: () => {}, disconnect: () => {} }
        }) as unknown as typeof IntersectionObserver

        try {
            const drawStatic = jest.fn()
            const canvas = renderCanvas(drawStatic)
            const entry = { isIntersecting: onScreen } as IntersectionObserverEntry
            act(() => onVisibilityChange([entry], {} as IntersectionObserver))
            drawStatic.mockClear()
            jest.useFakeTimers()

            viewport.scale = zoom
            Object.defineProperty(window, 'devicePixelRatio', { value: dpr, configurable: true })
            act(() => {
                onViewportResize()
                jest.runAllTimers()
            })
            // The settled repaint commits a state update, and the draw loop paints in the next frame.
            act(() => jest.runAllTimers())

            expect(canvas.width).toBe(expectedWidth)
            expect(drawStatic).toHaveBeenCalledTimes(repaints)
        } finally {
            jest.useRealTimers()
            globalThis.IntersectionObserver = originalIntersectionObserver
            Object.defineProperty(window, 'visualViewport', { value: undefined, configurable: true })
            Object.defineProperty(window, 'devicePixelRatio', { value: originalDpr, configurable: true })
        }
    })

    it('repaints against a restored backing store after the 2D context is lost', () => {
        const drawStatic = jest.fn()
        const canvas = renderCanvas(drawStatic)
        expect(drawStatic).toHaveBeenCalled()

        drawStatic.mockClear()
        act(() => {
            canvas.dispatchEvent(new Event('contextrestored'))
        })

        expect(drawStatic).toHaveBeenCalled()
        expect(canvas.width).toBe(mockRect.width)
    })
})
