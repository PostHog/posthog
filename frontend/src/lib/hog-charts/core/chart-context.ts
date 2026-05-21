import { createContext, useContext } from 'react'

import type { ChartDimensions, ChartScales, ChartTheme, ResolvedSeries, ResolveValueFn } from './types'

/** Axis-related state exposed to overlays. */
export interface ChartAxisContextValue {
    /** `horizontal` swaps which axis carries the value scale (`scales.y` returns x-pixels). */
    orientation: 'vertical' | 'horizontal'
    /** Resolved x-axis tick formatter (the same one `<AxisLabels>` uses). Overlays that
     *  need to align with the visible tick set should read this rather than recompute. */
    xTickFormatter: ((value: string, index: number) => string | null) | undefined
    /** True for BarChart `barLayout: 'percent'` / LineChart `percentStackView`. Overlays
     *  that format values can use this to default to a percent formatter. */
    isPercent: boolean
}

/** Layout-stable values exposed to overlays. Identity does NOT change on hover —
 *  consumers reading from {@link useChartLayout} won't re-render on mousemove. */
export interface ChartLayoutContextValue<Meta = unknown> {
    /** Computed plot/container dimensions in CSS pixels. */
    dimensions: ChartDimensions
    /** X-axis labels. */
    labels: string[]
    /** Series with fallback colors already applied (post `theme.colors`). */
    series: ResolvedSeries<Meta>[]
    /** Scale functions for mapping data to pixel coordinates. */
    scales: ChartScales
    /** Theme passed to the chart. Use {@link ChartTheme.backgroundColor} for borders/fills
     *  that need to blend into the chart background (e.g. value-label borders). */
    theme: ChartTheme
    /** Resolves the y-value for a series at a given index. Honors stacking when the
     *  parent chart provides a stacked resolver — overlays should always go through
     *  this rather than reading `series.data[i]` directly. */
    resolveValue: ResolveValueFn
    /** Returns the current canvas bounding rect, or null if the canvas is unmounted.
     *  This is a getter (not a value) because DOMRect changes on scroll. Useful for
     *  custom overlays that portal positioned content outside the chart wrapper. */
    canvasBounds: () => DOMRect | null
    /** Axis-related state (orientation, x-axis formatter, value-scale flags). */
    axis: ChartAxisContextValue
}

/** Hover state isolated from layout so mousemoves don't invalidate every overlay.
 *  Only {@link Crosshair} (and consumers of {@link useChartHover}) re-render. */
export interface ChartHoverContextValue {
    /** Index of the currently hovered data point, or -1 when not hovering. */
    hoverIndex: number
}

/** Merged layout + hover shape returned by {@link useChart}. */
export interface BaseChartContext<Meta = unknown> extends ChartLayoutContextValue<Meta>, ChartHoverContextValue {}

export const ChartLayoutContext = createContext<ChartLayoutContextValue | null>(null)
export const ChartHoverContext = createContext<ChartHoverContextValue>({ hoverIndex: -1 })

/** Subscribes to layout-only context. Does NOT re-render on hover. Prefer this for
 *  overlays that don't need `hoverIndex` (axis labels, value labels, reference lines). */
export function useChartLayout<Meta = unknown>(): ChartLayoutContextValue<Meta> {
    const ctx = useContext(ChartLayoutContext)
    if (!ctx) {
        throw new Error('useChartLayout must be used inside a chart component (e.g. <LineChart>)')
    }
    return ctx as ChartLayoutContextValue<Meta>
}

/** Subscribes to hover-only context. Re-renders on every hover index change. */
export function useChartHover(): ChartHoverContextValue {
    return useContext(ChartHoverContext)
}

/** Back-compat hook that merges layout + hover. Consumers of this hook re-render on
 *  every mousemove. Prefer {@link useChartLayout} or {@link useChartHover} for
 *  granular subscriptions when you don't need both.
 *
 *  @remarks `Meta` is unverified — the cast trusts the caller to pass the same
 *  generic the chart was instantiated with. */
export function useChart<Meta = unknown>(): BaseChartContext<Meta> {
    const layout = useChartLayout<Meta>()
    const hover = useChartHover()
    // Plain spread — any caller of useChart() already re-renders on hover (the hover
    // context updates), so a memo here would never short-circuit and only adds overhead.
    return { ...layout, ...hover }
}
