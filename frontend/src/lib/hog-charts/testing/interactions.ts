import { fireEvent } from '@testing-library/react'

import { dimensions } from './jsdom'
import { waitForHogChartTooltip } from './tooltip'

/** Fire a mouseMove on a chart wrapper element at the pixel position
 *  corresponding to the given label index. */
export function hoverAtIndex(wrapper: HTMLElement, index: number, totalLabels: number): void {
    const step = dimensions.plotWidth / (totalLabels - 1)
    fireEvent.mouseMove(wrapper, {
        clientX: dimensions.plotLeft + step * index,
        clientY: dimensions.plotTop + dimensions.plotHeight / 2,
    })
}

export async function clickAtIndex(wrapper: HTMLElement, index: number, totalLabels: number): Promise<void> {
    hoverAtIndex(wrapper, index, totalLabels)
    // Wait for the hover state to flush — onClick reads tooltipCtx synchronously
    // to decide between pinning and onPointClick, and a stale null takes the wrong branch.
    await waitForHogChartTooltip()
    fireEvent.click(wrapper)
}
