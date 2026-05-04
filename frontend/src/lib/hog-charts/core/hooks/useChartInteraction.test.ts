import { renderHook, type RenderHookResult } from '@testing-library/react'
import { act } from 'react'

import { dimensions } from '../../testing'
import type { ChartScales } from '../types'
import { useChartInteraction } from './useChartInteraction'

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

    function renderInteraction(
        pinnable = true,
        onPointClick?: (data: unknown) => void
    ): RenderHookResult<ReturnType<typeof useChartInteraction>, unknown> {
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
                onPointClick: onPointClick as never,
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
        [
            'scroll outside the chart wrapper',
            () => {
                const outside = document.createElement('div')
                document.body.appendChild(outside)
                outside.dispatchEvent(new Event('scroll', { bubbles: true }))
                document.body.removeChild(outside)
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

    it('does not clear pinned tooltip on scroll inside the chart wrapper', () => {
        const { result } = renderInteraction()
        hoverAndPin(result)

        const scrollContainer = document.createElement('div')
        refs.wrapperRef.current!.appendChild(scrollContainer)

        act(() => {
            scrollContainer.dispatchEvent(new Event('scroll', { bubbles: true }))
        })

        expect(result.current.tooltipCtx?.isPinned).toBe(true)
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

    it('does not fire onPointClick when pinning engages (multi-series + pinnable)', () => {
        // Pinning is the consumer's first-click action; drilling-in is reserved for the
        // follow-up tooltip-row click. Firing onPointClick on the pin would open the
        // drill-in modal immediately and skip the row-selection step.
        const onPointClick = jest.fn()
        const { result } = renderInteraction(true, onPointClick)

        act(() => {
            simulateMouseMove(result.current.handlers, refs, 200, 100)
        })
        act(() => {
            result.current.handlers.onClick()
        })

        expect(onPointClick).not.toHaveBeenCalled()
        expect(result.current.tooltipCtx?.isPinned).toBe(true)
    })

    it('rebuilds the pinned tooltip when series data changes underneath the pin', () => {
        const { rerender, result } = renderHook(
            ({ s }: { s: typeof series }) =>
                useChartInteraction({
                    scales,
                    dimensions,
                    labels,
                    series: s,
                    canvasRef: refs.canvasRef,
                    wrapperRef: refs.wrapperRef,
                    showTooltip: true,
                    pinnable: true,
                    resolveValue: (sr, i) => sr.data[i],
                }),
            { initialProps: { s: series } }
        )

        act(() => {
            simulateMouseMove(result.current.handlers, refs, 200, 100)
        })
        act(() => {
            result.current.handlers.onClick()
        })
        expect(result.current.tooltipCtx?.isPinned).toBe(true)
        const initialIndex = result.current.tooltipCtx!.dataIndex
        const initialValue = result.current.tooltipCtx!.seriesData[0].value

        // Replace series with new data at the same indices.
        const updatedSeries = [
            { key: 'a', label: 'A', data: [999, 999, 999], color: '#f00' },
            { key: 'b', label: 'B', data: [777, 777, 777], color: '#0f0' },
        ]
        rerender({ s: updatedSeries })

        expect(result.current.tooltipCtx?.isPinned).toBe(true)
        expect(result.current.tooltipCtx?.dataIndex).toBe(initialIndex)
        expect(result.current.tooltipCtx?.seriesData[0].value).not.toBe(initialValue)
        expect(result.current.tooltipCtx?.seriesData[0].value).toBe(updatedSeries[0].data[initialIndex])
    })

    it('keeps the same tooltipCtx reference when a rerender produces value-equal series', () => {
        const { rerender, result } = renderHook(
            ({ s }: { s: typeof series }) =>
                useChartInteraction({
                    scales,
                    dimensions,
                    labels,
                    series: s,
                    canvasRef: refs.canvasRef,
                    wrapperRef: refs.wrapperRef,
                    showTooltip: true,
                    pinnable: true,
                    resolveValue: (sr, i) => sr.data[i],
                }),
            { initialProps: { s: series } }
        )

        act(() => {
            simulateMouseMove(result.current.handlers, refs, 200, 100)
        })
        act(() => {
            result.current.handlers.onClick()
        })
        expect(result.current.tooltipCtx?.isPinned).toBe(true)
        const initialCtx = result.current.tooltipCtx

        // Rerender with new series array containing new object identities but identical
        // values. The equivalence-bail in the rebuild effect should keep the prev ctx.
        const sameValuesNewIdentity = series.map((s) => ({ ...s }))
        rerender({ s: sameValuesNewIdentity })

        expect(result.current.tooltipCtx).toBe(initialCtx)
    })

    it('clears the pinned tooltip when labels shrink so the pinned dataIndex no longer exists', () => {
        const { rerender, result } = renderHook(
            ({ ls }: { ls: string[] }) =>
                useChartInteraction({
                    scales,
                    dimensions,
                    labels: ls,
                    series,
                    canvasRef: refs.canvasRef,
                    wrapperRef: refs.wrapperRef,
                    showTooltip: true,
                    pinnable: true,
                    resolveValue: (sr, i) => sr.data[i],
                }),
            { initialProps: { ls: labels } }
        )

        // Hover the last index then pin.
        act(() => {
            simulateMouseMove(result.current.handlers, refs, 300, 100)
        })
        act(() => {
            result.current.handlers.onClick()
        })
        expect(result.current.tooltipCtx?.isPinned).toBe(true)

        // Shrink labels so the pinned index is out of bounds.
        rerender({ ls: ['Mon'] })

        expect(result.current.tooltipCtx).toBeNull()
    })
})
