import { renderHook, type RenderHookResult } from '@testing-library/react'
import { act } from 'react'

import type { ChartDimensions, ChartScales } from '../types'
import { useChartInteraction } from './useChartInteraction'

const dimensions: ChartDimensions = {
    width: 800,
    height: 400,
    plotLeft: 48,
    plotTop: 16,
    plotWidth: 736,
    plotHeight: 352,
}

const scales: ChartScales = {
    x: (label: string) => ({ Mon: 100, Tue: 200, Wed: 300 })[label],
    y: (value: number) => 200 - value,
    yTicks: () => [0, 50, 100],
}

const series = [
    { key: 'a', label: 'A', data: [10, 20, 30], color: '#f00' },
    { key: 'b', label: 'B', data: [5, 15, 25], color: '#0f0' },
]

const labels = ['Mon', 'Tue', 'Wed']

function makeRefs(): { canvasRef: React.RefObject<HTMLCanvasElement>; wrapperRef: React.RefObject<HTMLDivElement> } {
    const wrapper = document.createElement('div')
    document.body.appendChild(wrapper)
    const canvas = document.createElement('canvas')
    wrapper.appendChild(canvas)
    // Mock getBoundingClientRect for canvas
    canvas.getBoundingClientRect = () =>
        ({
            x: 0,
            y: 0,
            width: 800,
            height: 400,
            top: 0,
            right: 800,
            bottom: 400,
            left: 0,
            toJSON: () => ({}),
        }) as DOMRect

    return {
        canvasRef: { current: canvas },
        wrapperRef: { current: wrapper },
    }
}

function simulateMouseMove(
    handlers: { onMouseMove: (e: React.MouseEvent<HTMLDivElement>) => void },
    refs: ReturnType<typeof makeRefs>,
    clientX: number,
    clientY: number
): void {
    const mockEvent = {
        clientX,
        clientY,
        currentTarget: refs.wrapperRef.current!,
    } as unknown as React.MouseEvent<HTMLDivElement>
    // Mock getBoundingClientRect on wrapper for the mouse move calculation
    refs.wrapperRef.current!.getBoundingClientRect = () =>
        ({
            x: 0,
            y: 0,
            width: 800,
            height: 400,
            top: 0,
            right: 800,
            bottom: 400,
            left: 0,
            toJSON: () => ({}),
        }) as DOMRect
    handlers.onMouseMove(mockEvent)
}

describe('useChartInteraction — tooltip pinning', () => {
    let refs: ReturnType<typeof makeRefs>

    beforeEach(() => {
        jest.useFakeTimers()
        refs = makeRefs()
    })

    afterEach(() => {
        jest.useRealTimers()
        if (refs.wrapperRef.current) {
            document.body.removeChild(refs.wrapperRef.current)
        }
    })

    function renderInteraction(pinnable = true): RenderHookResult<ReturnType<typeof useChartInteraction>, unknown> {
        return renderHook(() =>
            useChartInteraction({
                scales,
                dimensions,
                labels,
                series,
                canvasRef: refs.canvasRef,
                wrapperRef: refs.wrapperRef,
                showTooltip: true,
                pinnable,
                resolveValue: (s, i) => s.data[i],
            })
        )
    }

    function hoverAndPin(result: { current: ReturnType<typeof useChartInteraction> }): void {
        // Hover to create a tooltip context
        act(() => {
            simulateMouseMove(result.current.handlers, refs, 200, 100)
        })
        expect(result.current.tooltipCtx).not.toBeNull()

        // Click to pin
        act(() => {
            result.current.handlers.onClick()
        })
        expect(result.current.tooltipCtx?.isPinned).toBe(true)
    }

    it('starts with no tooltip', () => {
        const { result } = renderInteraction()
        expect(result.current.tooltipCtx).toBeNull()
        expect(result.current.hoverIndex).toBe(-1)
    })

    it('shows tooltip on hover', () => {
        const { result } = renderInteraction()

        act(() => {
            simulateMouseMove(result.current.handlers, refs, 200, 100)
        })

        expect(result.current.tooltipCtx).not.toBeNull()
        expect(result.current.hoverIndex).toBeGreaterThanOrEqual(0)
    })

    it('pins tooltip on click when pinnable and multiple series', () => {
        const { result } = renderInteraction()
        hoverAndPin(result)
    })

    it.each<[string, () => void]>([
        ['Escape key', () => document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape' }))],
        ['window scroll', () => window.dispatchEvent(new Event('scroll'))],
        [
            'nested element scroll (capture phase)',
            () => {
                const scrollContainer = document.createElement('div')
                refs.wrapperRef.current!.appendChild(scrollContainer)
                scrollContainer.dispatchEvent(new Event('scroll'))
            },
        ],
        [
            'click outside',
            () => {
                jest.runAllTimers()
                document.body.dispatchEvent(new MouseEvent('click', { bubbles: true }))
            },
        ],
    ])('clears pinned tooltip on %s', (_name, trigger) => {
        const { result } = renderInteraction()
        hoverAndPin(result)

        act(() => {
            trigger()
        })

        expect(result.current.tooltipCtx).toBeNull()
    })

    it('does not clear on non-Escape keys', () => {
        const { result } = renderInteraction()
        hoverAndPin(result)

        act(() => {
            document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Enter' }))
        })

        expect(result.current.tooltipCtx?.isPinned).toBe(true)
    })

    it('does not clear pinned tooltip on scroll inside the tooltip element', () => {
        const { result } = renderInteraction()
        hoverAndPin(result)

        // Simulate a scrollable element rendered inside the tooltip (it carries
        // the data-hog-charts-tooltip marker applied by the Tooltip overlay).
        const tooltipEl = document.createElement('div')
        tooltipEl.setAttribute('data-hog-charts-tooltip', '')
        const scrollableChild = document.createElement('div')
        tooltipEl.appendChild(scrollableChild)
        document.body.appendChild(tooltipEl)

        act(() => {
            scrollableChild.dispatchEvent(new Event('scroll', { bubbles: true }))
        })

        expect(result.current.tooltipCtx?.isPinned).toBe(true)

        document.body.removeChild(tooltipEl)
    })

    it('keeps tooltip on click inside wrapper', () => {
        const { result } = renderInteraction()
        hoverAndPin(result)

        act(() => {
            jest.runAllTimers()
        })

        act(() => {
            refs.wrapperRef.current!.dispatchEvent(new MouseEvent('click', { bubbles: true }))
        })

        expect(result.current.tooltipCtx?.isPinned).toBe(true)
    })

    it('unpins on second click on chart', () => {
        const { result } = renderInteraction()
        hoverAndPin(result)

        act(() => {
            result.current.handlers.onClick()
        })

        expect(result.current.tooltipCtx).toBeNull()
    })

    it('hover context does not have onUnpin', () => {
        const { result } = renderInteraction(true)

        act(() => {
            simulateMouseMove(result.current.handlers, refs, 200, 100)
        })

        expect(result.current.tooltipCtx?.isPinned).toBe(false)
        expect(result.current.tooltipCtx?.onUnpin).toBeUndefined()
    })

    it('pinned context has onUnpin', () => {
        const { result } = renderInteraction(true)
        hoverAndPin(result)

        expect(result.current.tooltipCtx?.isPinned).toBe(true)
        expect(result.current.tooltipCtx?.onUnpin).toBeInstanceOf(Function)
    })
})
