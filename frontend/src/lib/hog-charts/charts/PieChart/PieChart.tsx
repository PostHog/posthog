import React, { useCallback, useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
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
    /** Pixels the hovered slice slides out along its bisector. Default 16. */
    hoverOffset?: number
    /** Disable the hover pop-out — useful for snapshot stability or constrained layouts. */
    disableHoverOffset?: boolean
    /** Hide on-slice labels for slices smaller than this fraction of the total. Default 0.05. */
    minSlicePercentForLabel?: number
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

const DEFAULT_HOVER_OFFSET = 16
const DEFAULT_MIN_SLICE_PERCENT = 0.05

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
        hoverOffset = DEFAULT_HOVER_OFFSET,
        disableHoverOffset = false,
        minSlicePercentForLabel = DEFAULT_MIN_SLICE_PERCENT,
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

    const effectiveHoverOffset = disableHoverOffset ? 0 : hoverOffset

    const drawStatic = useCallback((args: ChartDrawArgs) => {
        const layout = getLayoutFromArgs<Meta>(args)
        if (!layout) {
            return
        }
        drawSlices(args.ctx, layout, args.theme, { skipIndex: -1, offset: 0 })
    }, [])

    const drawHover = useCallback(
        (args: ChartDrawArgs): boolean => {
            const layout = getLayoutFromArgs<Meta>(args)
            if (!layout || args.hoverIndex < 0) {
                return false
            }
            // Single-slice charts have nothing to pop out — drawing the offset would visually
            // shift the whole wheel.
            if (layout.slices.length <= 1 || effectiveHoverOffset === 0) {
                return false
            }
            // The mask step below relies on `theme.backgroundColor` to erase the static-canvas
            // copy of the slice. Without one, the popped-out slice would partially overlap the
            // original and smear — better to skip the pop-out than render that.
            if (!args.theme.backgroundColor) {
                return false
            }
            const slice = layout.slices[args.hoverIndex]
            if (!slice) {
                return false
            }
            // Two-pass paint on the (always-cleared) overlay canvas:
            //   1. Fill the slice's original footprint with the theme background. The overlay
            //      sits above the static canvas, so this *visually* erases the un-offset copy
            //      that `useChartDraw` re-paints on the static layer every render.
            //   2. Paint the slice in its real color at the offset position.
            // Without step 1 the offset copy only partially overlaps the original, leaving a
            // crescent of the un-offset slice visible — a smear, not a clean pop-out.
            drawSliceShape(args.ctx, slice, layout, {
                offset: 0,
                fillStyle: args.theme.backgroundColor,
                withStroke: undefined,
            })
            drawSliceShape(args.ctx, slice, layout, {
                offset: effectiveHoverOffset,
                fillStyle: slice.color,
                withStroke: layout.slices.length > 1 ? args.theme.backgroundColor : undefined,
            })
            return true
        },
        [effectiveHoverOffset]
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
            hitOuterSlack={effectiveHoverOffset}
            className={className}
            dataAttr={dataAttr}
        >
            <SliceLabels
                valueFormatter={valueFormatter}
                showValueOnSlice={showValueOnSlice}
                showLabelOnSlice={showLabelOnSlice}
                minSlicePercentForLabel={minSlicePercentForLabel}
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
    skipIndex: number
    offset: number
}

function drawSlices<Meta>(
    ctx: CanvasRenderingContext2D,
    layout: PieLayout<Meta>,
    theme: ChartTheme,
    { skipIndex, offset }: DrawSlicesOptions
): void {
    for (let i = 0; i < layout.slices.length; i++) {
        if (i === skipIndex) {
            continue
        }
        drawSlice(ctx, layout.slices[i], layout, theme, { offset })
    }
}

interface DrawSliceOptions {
    offset: number
}

function drawSlice<Meta>(
    ctx: CanvasRenderingContext2D,
    slice: PieLayout<Meta>['slices'][number],
    layout: PieLayout<Meta>,
    theme: ChartTheme,
    { offset }: DrawSliceOptions
): void {
    // Inter-slice stroke in the theme background — visually separates adjacent slices
    // without a heavy outline. Skipped when there's only one slice (no neighbour to separate from).
    const withStroke = layout.slices.length > 1 ? theme.backgroundColor : undefined
    drawSliceShape(ctx, slice, layout, { offset, fillStyle: slice.color, withStroke })
}

interface DrawSliceShapeOptions {
    offset: number
    fillStyle: string
    /** Inter-slice stroke color (typically `theme.backgroundColor`). Omit to skip stroking. */
    withStroke: string | undefined
}

/** Lower-level slice painter — takes explicit fill / stroke so the hover layer can both
 *  mask (background fill, no stroke) and re-paint (slice color, with stroke) using the same
 *  arc geometry. */
function drawSliceShape<Meta>(
    ctx: CanvasRenderingContext2D,
    slice: PieLayout<Meta>['slices'][number],
    layout: PieLayout<Meta>,
    { offset, fillStyle, withStroke }: DrawSliceShapeOptions
): void {
    const halfPad = layout.padAngle / 2
    const start = slice.startAngle + halfPad
    const end = slice.endAngle - halfPad
    if (start >= end) {
        return
    }
    const offsetX = offset === 0 ? 0 : Math.sin(slice.centroidAngle) * offset
    const offsetY = offset === 0 ? 0 : -Math.cos(slice.centroidAngle) * offset
    const cx = layout.cx + offsetX
    const cy = layout.cy + offsetY

    // Canvas arc convention: 0 = 3 o'clock, increasing clockwise. d3.pie uses
    // 0 = 12 o'clock. Subtract π/2 to align.
    const cStart = start - Math.PI / 2
    const cEnd = end - Math.PI / 2

    ctx.fillStyle = fillStyle
    ctx.beginPath()
    if (layout.innerRadius > 0) {
        ctx.arc(cx, cy, layout.outerRadius, cStart, cEnd, false)
        ctx.arc(cx, cy, layout.innerRadius, cEnd, cStart, true)
    } else {
        ctx.moveTo(cx, cy)
        ctx.arc(cx, cy, layout.outerRadius, cStart, cEnd, false)
    }
    ctx.closePath()
    ctx.fill()

    if (withStroke) {
        ctx.lineWidth = 1
        ctx.strokeStyle = withStroke
        ctx.stroke()
    }
}
