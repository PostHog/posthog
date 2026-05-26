import React, { useCallback, useMemo } from 'react'

import type { PieLayout } from '../charts/PieChart/computePieLayout'
import { DefaultTooltip } from '../overlays/DefaultTooltip'
import { Tooltip } from '../overlays/Tooltip'
import { ChartHoverContext, ChartLayoutContext } from './chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from './chart-context'
import { useChartCanvas } from './hooks/useChartCanvas'
import { useChartDraw } from './hooks/useChartDraw'
import { useRadialInteraction } from './hooks/useRadialInteraction'
import type { RadialSlicePayload } from './hooks/useRadialInteraction'
import { RadialLayoutContext } from './radial-context'
import type { RadialLayoutContextValue } from './radial-context'
import type {
    ChartDrawArgs,
    ChartMargins,
    ChartScales,
    ChartTheme,
    ResolvedSeries,
    Series,
    TooltipContext,
} from './types'
import { defaultResolveValue } from './types'

const OVERLAY_STYLE: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    pointerEvents: 'none',
}
const WRAPPER_STYLE_BASE: React.CSSProperties = {
    position: 'relative',
    width: '100%',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
}
const WRAPPER_STYLE_DEFAULT: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'default' }
const WRAPPER_STYLE_POINTER: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'pointer' }

const STATIC_CANVAS_STYLE: React.CSSProperties = { position: 'absolute', top: 0, left: 0 }
const OVERLAY_CANVAS_STYLE: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    pointerEvents: 'none',
}

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
    drawHover: (args: ChartDrawArgs) => void
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    showTooltip?: boolean
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    /** Slack beyond `outerRadius` for hit-testing — typically the hover pop-out distance. */
    hitOuterSlack?: number
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
    tooltip: renderTooltip = DefaultTooltip,
    showTooltip = true,
    onSliceClick,
    hitOuterSlack = 0,
    className,
    dataAttr,
    children,
}: RadialChartProps<Meta>): React.ReactElement {
    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({
        margins: RADIAL_MARGINS,
    })

    const coloredSeries = useMemo<ResolvedSeries<Meta>[]>(
        () =>
            series.map((s, i) => ({
                ...s,
                color: s.color || theme.colors[i % theme.colors.length],
            })),
        [series, theme.colors]
    )

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
    })

    const ariaLabel = useMemo(() => {
        const visible = coloredSeries.reduce((n, s) => n + (s.visibility?.excluded ? 0 : 1), 0)
        return `Pie chart with ${visible} slices`
    }, [coloredSeries])

    const wrapperStyle = hoverIndex >= 0 && onSliceClick ? WRAPPER_STYLE_POINTER : WRAPPER_STYLE_DEFAULT

    const canvasBounds = useCallback(
        (): DOMRect | null => canvasRef.current?.getBoundingClientRect() ?? null,
        [canvasRef]
    )

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
                    <div
                        ref={wrapperRef}
                        className={className}
                        data-attr={dataAttr}
                        style={wrapperStyle}
                        onMouseMove={handlers.onMouseMove}
                        onMouseLeave={handlers.onMouseLeave}
                        onClick={handlers.onClick}
                    >
                        <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={STATIC_CANVAS_STYLE} />
                        <canvas ref={overlayCanvasRef} aria-hidden="true" style={OVERLAY_CANVAS_STYLE} />

                        {dimensions && layout && (
                            <div style={OVERLAY_STYLE}>
                                {children}
                                {tooltipCtx && showTooltip && (
                                    <Tooltip
                                        context={tooltipCtx}
                                        renderTooltip={renderTooltip}
                                        placement="follow-data"
                                    />
                                )}
                            </div>
                        )}
                    </div>
                </ChartHoverContext.Provider>
            </RadialLayoutContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
