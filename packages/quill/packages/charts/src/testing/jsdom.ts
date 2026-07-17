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

/** Pixel position (client coords) of a given label index, vertically centered in the plot. */
export function clientForIndex(index: number, totalLabels: number): { clientX: number; clientY: number } {
    const step = dimensions.plotWidth / Math.max(1, totalLabels - 1)
    return {
        clientX: dimensions.plotLeft + step * index,
        clientY: dimensions.plotTop + dimensions.plotHeight / 2,
    }
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

    // Ensure `performance` is available in jsdom — the hover animation hook
    // calls `performance.now()` and older jsdom versions don't expose it.
    if (typeof global.performance === 'undefined') {
        global.performance = { now: () => 0 } as unknown as Performance
    }

    return () => {
        global.requestAnimationFrame = original
    }
}

let jsdomReady = false

/** Idempotent sibling of {@link setupJsdom} + {@link setupSyncRaf}. Called automatically by
 *  `renderHogChart` so simple tests don't need a beforeEach for the mocks; they're installed
 *  once for the test run and never torn down (cheap, and `getBoundingClientRect` stubbing is
 *  harmless to leave on for non-chart code in the same file). Tests that want fine-grained
 *  teardown can use the explicit `setupJsdom()` / `setupSyncRaf()` pair instead. */
export function ensureJsdom(): void {
    if (jsdomReady) {
        return
    }
    jsdomReady = true
    setupJsdom()
    setupSyncRaf()
}
