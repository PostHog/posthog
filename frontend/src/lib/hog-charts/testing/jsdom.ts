import { DEFAULT_MARGINS } from '../core/hooks/useChartMargins'
import type { ChartDimensions, ResolvedSeries, Series } from '../core/types'

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

export function makeSeries(overrides: Partial<Series> & { key: string; data: number[] }): ResolvedSeries {
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

/** Run requestAnimationFrame callbacks synchronously for the duration of a
 *  test. Use when the test needs to inspect what the chart drew before the
 *  static-layer RAF would normally fire. Call in beforeEach, and call the
 *  returned cleanup function in afterEach. */
export function setupSyncRaf(): () => void {
    const original = global.requestAnimationFrame
    global.requestAnimationFrame = ((cb: FrameRequestCallback) => {
        cb(0)
        return 0
    }) as typeof global.requestAnimationFrame
    return () => {
        global.requestAnimationFrame = original
    }
}
