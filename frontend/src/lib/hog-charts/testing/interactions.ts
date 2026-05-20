import { act, fireEvent } from '@testing-library/react'

import { dimensions } from './jsdom'
import { waitForHogChartTooltip } from './tooltip'

function clientForIndex(index: number, totalLabels: number): { clientX: number; clientY: number } {
    const step = dimensions.plotWidth / Math.max(1, totalLabels - 1)
    return {
        clientX: dimensions.plotLeft + step * index,
        clientY: dimensions.plotTop + dimensions.plotHeight / 2,
    }
}

/** Fire a mouseMove on a chart wrapper element at the pixel position
 *  corresponding to the given label index. */
export function hoverAtIndex(wrapper: HTMLElement, index: number, totalLabels: number): void {
    act(() => {
        fireEvent.mouseMove(wrapper, clientForIndex(index, totalLabels))
    })
}

export async function clickAtIndex(wrapper: HTMLElement, index: number, totalLabels: number): Promise<void> {
    hoverAtIndex(wrapper, index, totalLabels)
    // Wait for the hover state to flush — onClick reads tooltipCtx synchronously
    // to decide between pinning and onPointClick, and a stale null takes the wrong branch.
    await waitForHogChartTooltip()
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
