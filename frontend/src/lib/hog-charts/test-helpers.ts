import { fireEvent, waitFor } from '@testing-library/react'

import { DEFAULT_MARGINS } from './core/Chart'
import type { ChartDimensions, Series } from './core/types'

export const dimensions: ChartDimensions = {
    width: 800,
    height: 400,
    plotLeft: DEFAULT_MARGINS.left,
    plotTop: DEFAULT_MARGINS.top,
    plotWidth: 800 - DEFAULT_MARGINS.left - DEFAULT_MARGINS.right,
    plotHeight: 400 - DEFAULT_MARGINS.top - DEFAULT_MARGINS.bottom,
}

export const mockRect: DOMRect = {
    x: 0,
    y: 0,
    width: dimensions.width,
    height: dimensions.height,
    top: 0,
    left: 0,
    bottom: dimensions.height,
    right: dimensions.width,
    toJSON: () => ({}),
}

export function makeSeries(overrides: Partial<Series> & { key: string; data: number[] }): Series {
    return { label: overrides.key, color: '#000', ...overrides }
}

/** Mock ResizeObserver and getBoundingClientRect so hog-charts components
 *  render with real dimensions in jsdom. Call in beforeEach, and call the
 *  returned cleanup function in afterEach. */
export function setupJsdom(): () => void {
    if (typeof global.ResizeObserver === 'undefined') {
        global.ResizeObserver = class {
            observe(): void {}
            unobserve(): void {}
            disconnect(): void {}
        } as unknown as typeof ResizeObserver
    }
    const spy = jest.spyOn(Element.prototype, 'getBoundingClientRect').mockReturnValue(mockRect)
    return () => spy.mockRestore()
}

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
    await waitFor(
        () => {
            if (!document.querySelector('[data-hog-charts-tooltip]')) {
                throw new Error('tooltip not yet rendered')
            }
        },
        { timeout: 3000 }
    )
    fireEvent.click(wrapper)
}
