import React, { useEffect, useMemo } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useChartCanvas } from '../../core/hooks/useChartCanvas'
import type { ChartMargins, ChartTheme } from '../../core/types'
import { drawPieSlices, drawSliceLabels } from './utils/pie-canvas'
import { computePieLayout, computeSliceAngles, DEFAULT_START_ANGLE, type ResolvedPieSlice } from './utils/pie-layout'

const WRAPPER_STYLE: React.CSSProperties = {
    position: 'relative',
    width: '100%',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
    cursor: 'default',
}
const CANVAS_STYLE: React.CSSProperties = { position: 'absolute', top: 0, left: 0 }

const DEFAULT_PIE_MARGINS: ChartMargins = { top: 12, right: 12, bottom: 12, left: 12 }
// Reserved breathing room from the canvas edge so on-slice value labels don't get clipped.
// Exposed as `hoverOffset` to `computePieLayout`; here it's a fixed visual margin.
const EDGE_PADDING_PX = 16
const DEFAULT_VALUE_LABEL_MIN_PERCENT = 5

const defaultValueFormatter = (value: number): string => value.toLocaleString()

/** A single slice of the pie. */
export interface PieSlice<Meta = unknown> {
    /** Unique identifier — used to key DOM nodes and survive re-ordering across renders. */
    key: string
    /** Human-readable name shown in value labels. */
    label: string
    /** Numeric value for this slice. Non-positive slices are filtered out. */
    value: number
    /** CSS color string. When omitted the chart picks one from `theme.colors` by slice index. */
    color?: string
    /** Arbitrary consumer data attached to the slice. */
    meta?: Meta
}

/** Slice after `theme.colors` has been applied — colour is guaranteed. */
export type ResolvedPieSliceWithMeta<Meta = unknown> = PieSlice<Meta> & { color: string }

export interface PieChartConfig {
    /** Donut hole, 0–1 fraction of the outer radius. Defaults to 0 (full pie). */
    innerRadius?: number
    /** Slices below this percentage of the total skip their value label. Defaults to 5. */
    valueLabelMinPercent?: number
    /** Show numeric value labels on slices large enough to fit. Defaults to true. */
    showValuesOnSlices?: boolean
    /** When set, draws the slice label instead of the numeric value on each slice. */
    showLabelsOnSlices?: boolean
    /** Formats numeric values on slice labels. */
    valueFormatter?: (value: number) => string
    /** Radians of gap between adjacent slices. Defaults to 0. */
    slicePadding?: number
    /** Angle (radians) at which the first slice starts. Defaults to -π/2 (12 o'clock). */
    startAngle?: number
}

export interface PieChartProps<Meta = unknown> {
    /** Slices to render. Non-positive values are filtered out; the chart shows an empty state
     *  when no slices remain. */
    slices: PieSlice<Meta>[]
    theme: ChartTheme
    config?: PieChartConfig
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    /** Body shown when there are no positive slices. Defaults to a short text message. */
    emptyState?: React.ReactNode
    onError?: (error: Error, info: React.ErrorInfo) => void
}

export function PieChart<Meta = unknown>({ onError, ...rest }: PieChartProps<Meta>): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <PieChartInner {...rest} />
        </ChartErrorBoundary>
    )
}

function PieChartInner<Meta = unknown>({
    slices: rawSlices,
    theme,
    config,
    className,
    dataAttr,
    emptyState,
}: Omit<PieChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        innerRadius = 0,
        valueLabelMinPercent = DEFAULT_VALUE_LABEL_MIN_PERCENT,
        showValuesOnSlices = true,
        showLabelsOnSlices = false,
        valueFormatter = defaultValueFormatter,
        slicePadding = 0,
        startAngle = DEFAULT_START_ANGLE,
    } = config ?? {}

    const { canvasRef, wrapperRef, dimensions, ctx } = useChartCanvas({ margins: DEFAULT_PIE_MARGINS })

    // Apply theme palette and drop non-positive slices — they have no visual area and would
    // confuse rendering (zero-sweep arcs draw to nothing but still count as series).
    const visibleSlices = useMemo<ResolvedPieSliceWithMeta<Meta>[]>(() => {
        const out: ResolvedPieSliceWithMeta<Meta>[] = []
        let colorIndex = 0
        for (const slice of rawSlices) {
            if (!(slice.value > 0)) {
                continue
            }
            out.push({
                ...slice,
                color: slice.color || theme.colors[colorIndex % theme.colors.length],
            })
            colorIndex += 1
        }
        return out
    }, [rawSlices, theme.colors])

    const total = useMemo(() => visibleSlices.reduce((sum, s) => sum + s.value, 0), [visibleSlices])

    const layout = useMemo(() => {
        if (!dimensions) {
            return null
        }
        return computePieLayout(dimensions, { innerRadius, hoverOffset: EDGE_PADDING_PX })
    }, [dimensions, innerRadius])

    const sliceAngles = useMemo(
        () => computeSliceAngles(visibleSlices as ResolvedPieSlice[], total, startAngle),
        [visibleSlices, total, startAngle]
    )

    useEffect(() => {
        if (!ctx || !dimensions || !layout) {
            return
        }
        let cancelled = false
        const raf = requestAnimationFrame(() => {
            if (cancelled) {
                return
            }
            const dpr = window.devicePixelRatio || 1
            ctx.save()
            ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
            ctx.clearRect(0, 0, dimensions.width, dimensions.height)

            drawPieSlices(ctx, layout, visibleSlices as ResolvedPieSlice[], sliceAngles, {
                hoverIndex: -1,
                hoverOffset: 0,
                slicePadding,
            })

            if (showValuesOnSlices || showLabelsOnSlices) {
                drawSliceLabels(ctx, layout, visibleSlices as ResolvedPieSlice[], sliceAngles, {
                    minFraction: valueLabelMinPercent / 100,
                    mode: showLabelsOnSlices ? 'label' : 'value',
                    valueFormatter,
                    hoverIndex: -1,
                    hoverOffset: 0,
                })
            }
            ctx.restore()
        })
        return () => {
            cancelled = true
            cancelAnimationFrame(raf)
        }
    }, [
        ctx,
        dimensions,
        layout,
        sliceAngles,
        visibleSlices,
        slicePadding,
        showValuesOnSlices,
        showLabelsOnSlices,
        valueLabelMinPercent,
        valueFormatter,
    ])

    const ariaLabel = `Chart with ${visibleSlices.length} data series`

    if (visibleSlices.length === 0) {
        const fallback = emptyState ?? <span style={{ fontSize: 13, opacity: 0.6 }}>No data to display</span>
        return (
            <div
                ref={wrapperRef}
                className={className}
                data-attr={dataAttr}
                style={WRAPPER_STYLE}
                role="img"
                aria-label={ariaLabel}
            >
                <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={CANVAS_STYLE} />
                <div
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{
                        position: 'absolute',
                        inset: 0,
                        display: 'flex',
                        alignItems: 'center',
                        justifyContent: 'center',
                    }}
                >
                    {fallback}
                </div>
            </div>
        )
    }

    return (
        <div ref={wrapperRef} className={className} data-attr={dataAttr} style={WRAPPER_STYLE}>
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={CANVAS_STYLE} />
        </div>
    )
}
