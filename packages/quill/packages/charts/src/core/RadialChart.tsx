import React, { useMemo } from 'react'

import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { ChartHoverContext, ChartLayoutContext } from './chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from './chart-context'
import { ChartShell, countVisibleSeries, useCanvasBounds, useColoredSeries } from './chart-shell'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useRadialInteraction } from './hooks/useRadialInteraction'
import type { RadialSlicePayload } from './hooks/useRadialInteraction'
import { RadialLayoutContext } from './radial-context'
import type { RadialLayoutContextValue } from './radial-context'
import type { PieLayout } from './radial-layout'
import type {
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    DrawHoverResult,
    ResolvedSeries,
    Series,
    TooltipContext,
} from './types'
import { defaultResolveValue } from './types'

/** Near-zero margins — the radial chart computes center + radius from the full plot box and
 *  pulls the outer edge back via `radiusPadding`. The tiny pad here keeps slice strokes off
 *  the wrapper edge. */
export const RADIAL_MARGINS: ChartMargins = { top: 8, right: 8, bottom: 8, left: 8 }

/** Builds the geometry — and the matching ChartScales / RadialLayoutContext — from the
 *  current dimensions and resolved series. Pie/Donut variants supply their own builder. */
export type RadialLayoutBuilder<Meta = unknown> = (
    series: ResolvedSeries<Meta>[],
    dimensions: { plotLeft: number; plotTop: number; plotWidth: number; plotHeight: number }
) => PieLayout<Meta>

export interface RadialChartProps<Meta = unknown> {
    series: Series<Meta>[]
    theme: ChartTheme
    buildLayout: RadialLayoutBuilder<Meta>
    drawStatic: (args: ChartDrawArgs) => void
    drawHover: (args: ChartDrawArgs) => DrawHoverResult
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    showTooltip?: boolean
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    /** Slack beyond `outerRadius` for hit-testing — typically the hover pop-out distance. */
    hitOuterSlack?: number
    /** Duration (ms) of the hover-overlay transition. `0` disables (instant pop-out). */
    hoverAnimationMs?: number
    className?: string
    dataAttr?: string
    children?: React.ReactNode
}

export function RadialChart<Meta = unknown>({
    series,
    theme,
    buildLayout,
    drawStatic,
    drawHover,
    tooltip: renderTooltipProp,
    showTooltip = true,
    onSliceClick,
    hitOuterSlack = 0,
    hoverAnimationMs = 0,
    className,
    dataAttr,
    children,
}: RadialChartProps<Meta>): React.ReactElement {
    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({
        margins: RADIAL_MARGINS,
    })

    // Wrap DefaultTooltip in a JSX render function so its hooks run inside its own component
    // tree — calling it as a plain function would violate rules-of-hooks.
    const renderTooltip = useMemo<(ctx: TooltipContext<Meta>) => React.ReactNode>(
        () => renderTooltipProp ?? ((ctx: TooltipContext<Meta>) => <DefaultTooltip {...ctx} />),
        [renderTooltipProp]
    )

    const coloredSeries = useColoredSeries<Meta>(series, theme)

    const layout = useMemo(() => {
        if (!dimensions) {
            return null
        }
        return buildLayout(coloredSeries, dimensions)
    }, [coloredSeries, dimensions, buildLayout])

    // Expose the layout through a minimal ChartScales-shaped object so the shared `useChartDraw`
    // can pass it through `drawStatic` / `drawHover` without special-casing radial. Library code
    // never reads `_private`; consumers do via the typed radial context below.
    const scales = useMemo<ChartScales | null>(() => {
        if (!layout) {
            return null
        }
        return {
            x: () => undefined,
            y: () => 0,
            yTicks: () => [],
            _private: { __radialChart: { layout } },
        }
    }, [layout])

    const { hoverIndex, tooltipCtx, handlers } = useRadialInteraction<Meta>({
        layout,
        canvasRef,
        wrapperRef,
        showTooltip,
        onSliceClick,
        hitOuterSlack,
    })

    useChartDraw({
        ctx,
        overlayCtx,
        dimensions,
        scales,
        series: coloredSeries,
        // No x-axis category labels in a radial chart; preserve the contract by passing []. Slice
        // labels live in the SliceLabels overlay, which reads from the radial layout directly.
        labels: [],
        hoverIndex,
        hoverPosition: null,
        theme,
        drawStatic,
        drawHover,
        hoverAnimationMs,
    })

    const ariaLabel = useMemo(() => `Pie chart with ${countVisibleSeries(coloredSeries)} slices`, [coloredSeries])

    const canvasBounds = useCanvasBounds(canvasRef)

    // Provide the standard ChartLayoutContext so existing shared overlays (e.g. custom user
    // overlays accessing `useChartLayout()` for `theme`) continue to work. Most cartesian-only
    // overlays (AxisLabels, ValueLabels) shouldn't be used inside a radial chart, but the
    // context is still useful for theme + dimensions access.
    const layoutValue = useMemo<ChartLayoutContextValue<Meta> | null>(() => {
        if (!scales || !dimensions) {
            return null
        }
        return {
            scales,
            dimensions,
            labels: [],
            series: coloredSeries,
            theme,
            resolvePositionValue: defaultResolveValue,
            canvasBounds,
            axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
            yGutters: [],
        }
    }, [scales, dimensions, coloredSeries, theme, canvasBounds])

    const radialValue = useMemo<RadialLayoutContextValue<Meta> | null>(() => {
        if (!layout) {
            return null
        }
        return { layout, canvasBounds }
    }, [layout, canvasBounds])

    const hoverValue = useMemo<ChartHoverContextValue>(() => ({ hoverIndex }), [hoverIndex])

    return (
        <ChartLayoutContext.Provider value={layoutValue as ChartLayoutContextValue | null}>
            <RadialLayoutContext.Provider value={radialValue as RadialLayoutContextValue | null}>
                <ChartHoverContext.Provider value={hoverValue}>
                    <ChartShell
                        wrapperRef={wrapperRef}
                        canvasRef={canvasRef}
                        overlayCanvasRef={overlayCanvasRef}
                        className={className}
                        dataAttr={dataAttr}
                        pointer={hoverIndex >= 0 && !!onSliceClick}
                        ariaLabel={ariaLabel}
                        handlers={handlers}
                        showOverlay={!!(dimensions && layout)}
                    >
                        {children}
                        {tooltipCtx && showTooltip && (
                            <Tooltip context={tooltipCtx} renderTooltip={renderTooltip} placement="cursor" />
                        )}
                    </ChartShell>
                </ChartHoverContext.Provider>
            </RadialLayoutContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
