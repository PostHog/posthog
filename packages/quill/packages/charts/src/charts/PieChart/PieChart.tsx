import React, { useCallback, useMemo, useRef } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { mixColors } from '../../core/color-utils'
import type { RadialSlicePayload } from '../../core/hooks/useRadialInteraction'
import { useRadialLayout } from '../../core/radial-context'
import { RadialChart } from '../../core/RadialChart'
import type { RadialLayoutBuilder } from '../../core/RadialChart'
import type { ChartDrawArgs, ChartTheme, ResolvedSeries, Series, TooltipContext } from '../../core/types'
import { computePieLayout } from './computePieLayout'
import type { PieLayout } from './computePieLayout'
import { PieTooltip } from './PieTooltip'
import { SliceLabels } from './SliceLabels'

export interface PieChartConfig<Meta = unknown> {
    /** 0 = pie (default), 0.5 = donut. Clamped to [0, 0.95]. */
    innerRadiusRatio?: number
    /** Show the slice value above the slice (per Chart.js parity). Default true. */
    showValueOnSlice?: boolean
    /** Show the breakdown label above the slice. Default false. */
    showLabelOnSlice?: boolean
    /** Render slice values as percentages of total. Drives both axes-label-style formatting
     *  and the on-slice / tooltip formatting. */
    isPercent?: boolean
    /** Pixels the hovered slice's outer radius grows on hover (center stays fixed). Default 8. */
    hoverGrowth?: number
    /** Duration (ms) of the hover transition — the slice eases outward and brightens over this
     *  window rather than snapping. Default 150. `0` disables (instant). */
    hoverAnimationMs?: number
    /** Disable the hover grow effect — useful for snapshot stability or constrained layouts.
     *  Legacy name: this gates the whole hover effect (grow + brighten + dim), not just an offset. */
    disableHoverOffset?: boolean
    /** Hide on-slice labels for slices smaller than this fraction of the total. Default 0.05. */
    minSlicePercentForLabel?: number
    /** Where on-slice labels sit along the radius: 0 = center, 1 = outer edge. Default 0.5 (mid-slice).
     *  Higher values push labels toward the rim, onto the wider part of each wedge. */
    labelRadiusRatio?: number
    /** Radians gap between slices. Default 0. */
    padAngle?: number
    /** Slice ordering. `null` (default) preserves input order — needed for stable
     *  per-series colors. Pass a comparator on slice magnitudes to sort visually. */
    sort?: ((a: number, b: number) => number) | null
    /** Slice magnitude resolver. Defaults to sum of finite, positive entries in `series.data`. */
    sliceValue?: (series: ResolvedSeries<Meta>) => number
    /** Tooltip behavior. */
    tooltip?: {
        enabled?: boolean
    }
}

export interface PieChartProps<Meta = unknown> {
    series: Series<Meta>[]
    theme: ChartTheme
    config?: PieChartConfig<Meta>
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onSliceClick?: (payload: RadialSlicePayload<Meta>) => void
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    /** Custom value formatter used by the on-slice value label and the default tooltip.
     *  Receives the raw slice magnitude; the chart handles percent conversion when
     *  `isPercent` is on. */
    valueFormatter?: (value: number) => string
    /** Optional content rendered at the center of the chart — typically the aggregation
     *  total for a donut. Receives the layout so consumers can position custom content. */
    centerLabel?: React.ReactNode
    /** React children passed through to the radial overlay layer (custom decorations). */
    children?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const DEFAULT_HOVER_GROWTH = 8
const DEFAULT_HOVER_ANIMATION_MS = 150
const DEFAULT_MIN_SLICE_PERCENT = 0.05
const DEFAULT_LABEL_RADIUS_RATIO = 0.5
// Hovered slice eases toward white by this fraction at full hover — a subtle highlight.
const HOVER_HIGHLIGHT_TARGET = '#ffffff'
const HOVER_HIGHLIGHT_AMOUNT = 0.15
// Non-hovered slices ease toward the chart background by this fraction, fading into the
// backdrop so the hovered slice stands out.
const HOVER_DIM_AMOUNT = 0.55
// Used only when the theme omits `backgroundColor`. Assumes a light backdrop — consumers on a
// dark theme should set `theme.backgroundColor` so slices dim toward the dark surface instead.
const HOVER_DIM_TARGET_FALLBACK = '#ffffff'

function easeOutCubic(t: number): number {
    return 1 - Math.pow(1 - t, 3)
}

const CENTER_LABEL_STYLE: React.CSSProperties = {
    position: 'absolute',
    pointerEvents: 'none',
    transform: 'translate(-50%, -50%)',
    textAlign: 'center',
    whiteSpace: 'nowrap',
}

interface CenterLabelProps {
    children: React.ReactNode
    cx: number
    cy: number
}

function CenterLabel({ children, cx, cy }: CenterLabelProps): React.ReactElement {
    return <div style={{ ...CENTER_LABEL_STYLE, left: cx, top: cy }}>{children}</div>
}

export function PieChart<Meta = unknown>({ onError, ...rest }: PieChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <PieChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function defaultValueFormatter(value: number): string {
    return value.toLocaleString()
}

function PieChartInner<Meta = unknown>({
    series,
    theme,
    config,
    tooltip,
    onSliceClick,
    className,
    dataAttr,
    valueFormatter = defaultValueFormatter,
    centerLabel,
    children,
}: Omit<PieChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        innerRadiusRatio = 0,
        showValueOnSlice = true,
        showLabelOnSlice = false,
        isPercent = false,
        hoverGrowth = DEFAULT_HOVER_GROWTH,
        hoverAnimationMs = DEFAULT_HOVER_ANIMATION_MS,
        disableHoverOffset = false,
        minSlicePercentForLabel = DEFAULT_MIN_SLICE_PERCENT,
        labelRadiusRatio = DEFAULT_LABEL_RADIUS_RATIO,
        padAngle = 0,
        sort = null,
        sliceValue,
        tooltip: tooltipConfig,
    } = config ?? {}

    const showTooltip = tooltipConfig?.enabled !== false

    const buildLayout = useCallback<RadialLayoutBuilder<Meta>>(
        (resolvedSeries, dimensions) =>
            computePieLayout<Meta>({
                series: resolvedSeries,
                dimensions,
                sliceValue,
                innerRadiusRatio,
                padAngle,
                sort,
            }),
        [sliceValue, innerRadiusRatio, padAngle, sort]
    )

    const effectiveHoverGrowth = disableHoverOffset ? 0 : hoverGrowth
    const effectiveHoverAnimationMs = disableHoverOffset ? 0 : hoverAnimationMs

    // Backdrop-dim level (0 = none, 1 = full), held across slice crossings — see the ramp in
    // drawHover for why it can't be read straight off hoverProgress.
    const dimRef = useRef(0)

    const drawStatic = useCallback((args: ChartDrawArgs) => {
        const layout = getLayoutFromArgs<Meta>(args)
        if (!layout) {
            return
        }
        drawSlices(args.ctx, layout, { outerRadiusBoost: 0 })
    }, [])

    const drawHover = useCallback(
        (args: ChartDrawArgs): boolean => {
            const layout = getLayoutFromArgs<Meta>(args)
            // A lone full-circle slice has nothing to highlight against — growing it just
            // pulses the whole wheel.
            const slice = layout && args.hoverIndex >= 0 ? layout.slices[args.hoverIndex] : null
            if (!layout || !slice || layout.slices.length <= 1 || effectiveHoverGrowth === 0) {
                dimRef.current = 0
                return false
            }
            // The focused slice's growth + tint ease over `hoverProgress` (0→1 from useChartDraw's
            // RAF loop), so it swells and brightens rather than snapping.
            const eased = easeOutCubic(args.hoverProgress)
            // Ramp the backdrop dim with the same fade, but only ever upward: `hoverProgress`
            // resets to 0 on each hoverIndex change, so reading the dim straight off it would
            // flash the rest of the pie back to full color every time the cursor crosses into the
            // next slice. Holding the max keeps the backdrop steady (and lets an in-progress fade
            // continue) as you sweep across segments; it resets on hover-out (guard above).
            dimRef.current = Math.max(dimRef.current, eased * HOVER_DIM_AMOUNT)
            // Repaint every *other* slice over its static copy in a color faded toward the
            // background, dimming the rest so the hovered slice stands out. The fade fill must be
            // opaque — a translucent fill would composite against the full-color static slice
            // beneath the overlay and not dim at all.
            const dimTarget = args.theme.backgroundColor || HOVER_DIM_TARGET_FALLBACK
            for (let i = 0; i < layout.slices.length; i++) {
                if (i === args.hoverIndex) {
                    continue
                }
                const other = layout.slices[i]
                const faded = mixColors(other.color, dimTarget, dimRef.current)
                drawSliceShape(args.ctx, other, layout, { outerRadiusBoost: 0, fillStyle: faded })
            }
            // Hovered slice last, on top of the dimmed others.
            const outerRadiusBoost = eased * effectiveHoverGrowth
            const fillStyle = mixColors(slice.color, HOVER_HIGHLIGHT_TARGET, eased * HOVER_HIGHLIGHT_AMOUNT)
            drawSliceShape(args.ctx, slice, layout, { outerRadiusBoost, fillStyle })
            return true
        },
        [effectiveHoverGrowth]
    )

    const renderTooltip = useMemo(
        () =>
            tooltip ??
            ((ctx: TooltipContext<Meta>): React.ReactNode => (
                <PieTooltip ctx={ctx} valueFormatter={valueFormatter} isPercent={isPercent} />
            )),
        [tooltip, valueFormatter, isPercent]
    )

    return (
        <RadialChart<Meta>
            series={series}
            theme={theme}
            buildLayout={buildLayout}
            drawStatic={drawStatic}
            drawHover={drawHover}
            tooltip={renderTooltip}
            showTooltip={showTooltip}
            onSliceClick={onSliceClick}
            hitOuterSlack={effectiveHoverGrowth}
            hoverAnimationMs={effectiveHoverAnimationMs}
            className={className}
            dataAttr={dataAttr}
        >
            <SliceLabels
                valueFormatter={valueFormatter}
                showValueOnSlice={showValueOnSlice}
                showLabelOnSlice={showLabelOnSlice}
                minSlicePercentForLabel={minSlicePercentForLabel}
                labelRadiusRatio={labelRadiusRatio}
                isPercent={isPercent}
            />
            <PieCenterLabel>{centerLabel}</PieCenterLabel>
            {children}
        </RadialChart>
    )
}

function PieCenterLabel({ children }: { children: React.ReactNode }): React.ReactElement | null {
    const { layout } = useRadialLayout()
    if (!children) {
        return null
    }
    return (
        <CenterLabel cx={layout.cx} cy={layout.cy}>
            {children}
        </CenterLabel>
    )
}

function getLayoutFromArgs<Meta>(args: ChartDrawArgs): PieLayout<Meta> | null {
    const priv = args.scales._private as { __radialChart?: { layout: PieLayout<Meta> } } | undefined
    return priv?.__radialChart?.layout ?? null
}

interface DrawSlicesOptions {
    outerRadiusBoost: number
}

function drawSlices<Meta>(
    ctx: CanvasRenderingContext2D,
    layout: PieLayout<Meta>,
    { outerRadiusBoost }: DrawSlicesOptions
): void {
    for (let i = 0; i < layout.slices.length; i++) {
        drawSliceShape(ctx, layout.slices[i], layout, { outerRadiusBoost, fillStyle: layout.slices[i].color })
    }
}

interface DrawSliceShapeOptions {
    /** Pixels added to the outer radius (center fixed) — drives the hover grow. */
    outerRadiusBoost: number
    fillStyle: string
}

/** Lower-level slice painter — takes an explicit fill so the hover layer can re-paint a slice
 *  (grown + brightened) over its static base using the same center and angles. Slices are drawn
 *  borderless: with many thin wedges, an inter-slice stroke piles up into a white cone at the
 *  apex, so adjacent slices are separated by color alone (matching the legacy pie). */
function drawSliceShape<Meta>(
    ctx: CanvasRenderingContext2D,
    slice: PieLayout<Meta>['slices'][number],
    layout: PieLayout<Meta>,
    { outerRadiusBoost, fillStyle }: DrawSliceShapeOptions
): void {
    const halfPad = layout.padAngle / 2
    const start = slice.startAngle + halfPad
    const end = slice.endAngle - halfPad
    if (start >= end) {
        return
    }
    const { cx, cy, innerRadius } = layout
    const outerRadius = layout.outerRadius + outerRadiusBoost

    // Canvas arc convention: 0 = 3 o'clock, increasing clockwise. d3.pie uses
    // 0 = 12 o'clock. Subtract π/2 to align.
    const cStart = start - Math.PI / 2
    const cEnd = end - Math.PI / 2

    ctx.fillStyle = fillStyle
    ctx.beginPath()
    if (innerRadius > 0) {
        ctx.arc(cx, cy, outerRadius, cStart, cEnd, false)
        ctx.arc(cx, cy, innerRadius, cEnd, cStart, true)
    } else {
        ctx.moveTo(cx, cy)
        ctx.arc(cx, cy, outerRadius, cStart, cEnd, false)
    }
    ctx.closePath()
    ctx.fill()
}
