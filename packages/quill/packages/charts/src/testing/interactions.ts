import { act, fireEvent } from '@testing-library/react'

import { clientForIndex } from './jsdom'
import { waitForHogChartTooltip } from './tooltip'

/** Fire a mouseMove on a chart wrapper element at the pixel position
 *  corresponding to the given label index. */
export function hoverAtIndex(wrapper: HTMLElement, index: number, totalLabels: number): void {
    act(() => {
        fireEvent.mouseMove(wrapper, clientForIndex(index, totalLabels))
    })
}

/** Hover at the given label index, re-dispatching the mouseMove until the chart's
 *  tooltip portal mounts. The chart commits its scales/dimensions in a post-render
 *  effect (useChartCanvas), and onMouseMove is a no-op until that commit lands — so
 *  a single hover fired before the chart settles is silently dropped and the tooltip
 *  never appears. Polling the *trigger* (not just the result) makes the hover
 *  deterministic regardless of when the chart settles, without inflating timeouts. */
export async function hoverUntilTooltip(
    wrapper: HTMLElement,
    index: number,
    totalLabels: number,
    timeout = 3000
): Promise<HTMLElement> {
    return waitForHogChartTooltip(timeout, () => hoverAtIndex(wrapper, index, totalLabels))
}

export async function clickAtIndex(wrapper: HTMLElement, index: number, totalLabels: number): Promise<void> {
    // Re-hover until the tooltip flushes — onClick reads tooltipCtx synchronously to decide
    // between pinning and onPointClick, and a stale null takes the wrong branch.
    await hoverUntilTooltip(wrapper, index, totalLabels)
    fireEvent.click(wrapper)
}

// Fires mouseup on window (the chart's drag handler listens globally).
export function dragSelection(wrapper: HTMLElement, fromIndex: number, toIndex: number, totalLabels: number): void {
    const from = clientForIndex(fromIndex, totalLabels)
    const to = clientForIndex(toIndex, totalLabels)
    act(() => {
        fireEvent.mouseDown(wrapper, { button: 0, ...from })
        fireEvent.mouseMove(wrapper, to)
        fireEvent(window, new MouseEvent('mouseup', { bubbles: true, clientX: to.clientX, clientY: to.clientY }))
        fireEvent.click(wrapper, to)
    })
}
