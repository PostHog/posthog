import { render, type RenderResult } from '@testing-library/react'
import type { ReactNode } from 'react'

import { ChartHoverContext, ChartLayoutContext } from '../core/chart-context'
import type { BaseChartContext, ChartLayoutContextValue } from '../core/chart-context'
import type { ChartScales, ChartTheme, ResolvedSeries, ResolveValueFn } from '../core/types'
import { dimensions as DEFAULT_DIMENSIONS } from './jsdom'

const DEFAULT_THEME: ChartTheme = { colors: ['#000'], backgroundColor: '#ffffff' }
const DEFAULT_RESOLVE: ResolveValueFn = (s, i) => s.data[i] ?? 0

export interface OverlayContextOverrides {
    dimensions?: BaseChartContext['dimensions']
    labels?: string[]
    series?: ResolvedSeries[]
    theme?: ChartTheme
    resolveValue?: ResolveValueFn
    canvasBounds?: () => DOMRect | null
    axisOrientation?: 'vertical' | 'horizontal'
    isPercent?: boolean
    hoverIndex?: number
}

/** Build a fully-populated overlay context with sensible defaults. Required:
 *  `scales` (the overlay-under-test almost always needs control over these). */
export function makeOverlayContext(scales: ChartScales, overrides: OverlayContextOverrides = {}): BaseChartContext {
    return {
        dimensions: overrides.dimensions ?? DEFAULT_DIMENSIONS,
        labels: overrides.labels ?? [],
        series: overrides.series ?? [],
        scales,
        theme: overrides.theme ?? DEFAULT_THEME,
        resolveValue: overrides.resolveValue ?? DEFAULT_RESOLVE,
        canvasBounds: overrides.canvasBounds ?? (() => null),
        axisOrientation: overrides.axisOrientation ?? 'vertical',
        isPercent: overrides.isPercent ?? false,
        hoverIndex: overrides.hoverIndex ?? -1,
    }
}

/** Render an overlay component with explicit chart context — used to test overlays
 *  in isolation without booting a real chart. Pass hand-rolled scales so you can
 *  assert exact pixel positions without depending on d3's tick algorithm. */
export function renderOverlayInChart(node: ReactNode, ctx: BaseChartContext): RenderResult {
    const { hoverIndex, ...layout } = ctx
    const layoutValue: ChartLayoutContextValue = layout
    return render(
        <ChartLayoutContext.Provider value={layoutValue}>
            <ChartHoverContext.Provider value={{ hoverIndex }}>{node}</ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
