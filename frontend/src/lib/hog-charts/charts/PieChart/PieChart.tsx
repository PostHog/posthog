import { flip, FloatingPortal, offset, shift, useFloating, type VirtualElement } from '@floating-ui/react'
import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'

import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useChartCanvas } from '../../core/hooks/useChartCanvas'
import type { ChartMargins, ChartTheme, Series, TooltipConfig, TooltipContext } from '../../core/types'
import { PieTooltip } from './PieTooltip'
import { drawPieSlices, drawSliceLabels, highlightColorFor } from './utils/pie-canvas'
import {
    computePieLayout,
    computeSliceAngles,
    DEFAULT_START_ANGLE,
    hitTestSlice,
    type PieLayout,
    type ResolvedPieSlice,
    type SliceAngle,
} from './utils/pie-layout'

const WRAPPER_STYLE_BASE: React.CSSProperties = {
    position: 'relative',
    width: '100%',
    flex: 1,
    minHeight: 0,
    overflow: 'hidden',
}
const WRAPPER_STYLE_DEFAULT: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'default' }
const WRAPPER_STYLE_POINTER: React.CSSProperties = { ...WRAPPER_STYLE_BASE, cursor: 'pointer' }
const CANVAS_STYLE: React.CSSProperties = { position: 'absolute', top: 0, left: 0 }

const DEFAULT_PIE_MARGINS: ChartMargins = { top: 12, right: 12, bottom: 12, left: 12 }
const DEFAULT_HOVER_OFFSET = 16
const DEFAULT_VALUE_LABEL_MIN_PERCENT = 5
const DEFAULT_TOOLTIP_Z_INDEX = 9999
const TOOLTIP_MIDDLEWARE = [offset(12), flip(), shift({ padding: 8 })]

const defaultValueFormatter = (value: number): string => value.toLocaleString()

/** A single slice of the pie. */
export interface PieSlice<Meta = unknown> {
    /** Unique identifier — used to key DOM nodes and survive re-ordering across renders. */
    key: string
    /** Human-readable name shown in the tooltip and value labels. */
    label: string
    /** Numeric value for this slice. Non-positive slices are filtered out. */
    value: number
    /** CSS color string. When omitted the chart picks one from `theme.colors` by slice index. */
    color?: string
    /** Arbitrary consumer data attached to the slice — flows through to the synthetic
     *  `Series.meta` exposed via `TooltipContext.seriesData[].series.meta`, and to the
     *  slice-click callback. */
    meta?: Meta
}

/** Slice after `theme.colors` has been applied — colour is guaranteed. */
export type ResolvedPieSliceWithMeta<Meta = unknown> = PieSlice<Meta> & { color: string }

export interface PieChartConfig {
    /** Donut hole, 0–1 fraction of the outer radius. Defaults to 0 (full pie). */
    innerRadius?: number
    /** Pixels to pop a hovered slice out along its bisector. Defaults to 16; set to 0 to disable. */
    hoverOffset?: number
    /** Slices below this percentage of the total skip their value label. Defaults to 5. */
    valueLabelMinPercent?: number
    /** Show numeric value labels on slices large enough to fit. Defaults to true. */
    showValuesOnSlices?: boolean
    /** When set, draws the slice label instead of the numeric value on each slice. */
    showLabelsOnSlices?: boolean
    /** Formats numeric values everywhere — value labels and the default tooltip. */
    valueFormatter?: (value: number) => string
    /** Tooltip behaviour. Defaults to enabled, not pinnable. */
    tooltip?: TooltipConfig
    /** Radians of gap between adjacent slices. Defaults to 0. */
    slicePadding?: number
    /** Angle (radians) at which the first slice starts. Defaults to -π/2 (12 o'clock). */
    startAngle?: number
}

export interface PieSliceClickData<Meta = unknown> {
    /** Index into the *filtered* (positive-value) slice array. */
    sliceIndex: number
    slice: ResolvedPieSliceWithMeta<Meta>
    value: number
    /** Slice's percentage of the total (0–100). */
    percent: number
    total: number
}

export interface PieChartProps<Meta = unknown> {
    /** Slices to render. Non-positive values are filtered out; the chart shows an empty state
     *  when no slices remain. */
    slices: PieSlice<Meta>[]
    theme: ChartTheme
    config?: PieChartConfig
    /** Override the tooltip body. Receives the same `TooltipContext` every hog-chart emits;
     *  each slice is a synthetic one-point series so `seriesData[dataIndex]` is the hovered
     *  slice, and `seriesData.reduce(...)` gives the total. */
    tooltip?: (ctx: TooltipContext<Meta>) => React.ReactNode
    onSliceClick?: (data: PieSliceClickData<Meta>) => void
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
    tooltip: tooltipRenderProp,
    onSliceClick,
    className,
    dataAttr,
    emptyState,
}: Omit<PieChartProps<Meta>, 'onError'>): React.ReactElement {
    const {
        innerRadius = 0,
        hoverOffset = DEFAULT_HOVER_OFFSET,
        valueLabelMinPercent = DEFAULT_VALUE_LABEL_MIN_PERCENT,
        showValuesOnSlices = true,
        showLabelsOnSlices = false,
        valueFormatter = defaultValueFormatter,
        tooltip: tooltipConfig,
        slicePadding = 0,
        startAngle = DEFAULT_START_ANGLE,
    } = config ?? {}
    const { enabled: showTooltip = true, pinnable: pinnableTooltip = false } = tooltipConfig ?? {}

    const { canvasRef, wrapperRef, dimensions, ctx } = useChartCanvas({ margins: DEFAULT_PIE_MARGINS })

    // Apply theme palette and drop non-positive slices — they have no visual area and would
    // confuse hit testing (zero-sweep arcs match every cursor angle).
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

    const layout = useMemo<PieLayout | null>(() => {
        if (!dimensions) {
            return null
        }
        return computePieLayout(dimensions, { innerRadius, hoverOffset })
    }, [dimensions, innerRadius, hoverOffset])

    const sliceAngles = useMemo<SliceAngle[]>(
        () => computeSliceAngles(visibleSlices as ResolvedPieSlice[], total, startAngle),
        [visibleSlices, total, startAngle]
    )

    const [hoverIndex, setHoverIndex] = useState<number>(-1)
    const [hoverPosition, setHoverPosition] = useState<{ x: number; y: number } | null>(null)
    const [isPinned, setIsPinned] = useState<boolean>(false)
    const hoverIndexRef = useRef(hoverIndex)
    hoverIndexRef.current = hoverIndex

    const clearHover = useCallback(() => {
        setHoverIndex(-1)
        setHoverPosition(null)
        setIsPinned(false)
    }, [])

    const unpin = useCallback(() => setIsPinned(false), [])

    // Reset hover state when the slice set changes — index/position pointers into the
    // previous geometry are nonsense against the new one.
    useEffect(() => {
        setHoverIndex(-1)
        setHoverPosition(null)
        setIsPinned(false)
    }, [visibleSlices])

    // Drawing — one layer is enough since hover rearranges the geometry (slice pops out)
    // and value labels track the hover offset. Splitting static / hover would force the
    // static layer to redraw on every hover anyway.
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

            // Tint the hovered slice darker by mutating its color in the array we pass to
            // drawPieSlices — cheaper than a separate overlay pass since geometry already
            // shifts on hover.
            const slicesForDraw =
                hoverIndex >= 0
                    ? visibleSlices.map((s, i) => (i === hoverIndex ? { ...s, color: highlightColorFor(s.color) } : s))
                    : visibleSlices

            drawPieSlices(ctx, layout, slicesForDraw as ResolvedPieSlice[], sliceAngles, {
                hoverIndex,
                hoverOffset,
                slicePadding,
            })

            if (showValuesOnSlices || showLabelsOnSlices) {
                drawSliceLabels(ctx, layout, visibleSlices as ResolvedPieSlice[], sliceAngles, {
                    minFraction: valueLabelMinPercent / 100,
                    mode: showLabelsOnSlices ? 'label' : 'value',
                    valueFormatter,
                    hoverIndex,
                    hoverOffset,
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
        hoverIndex,
        hoverOffset,
        slicePadding,
        showValuesOnSlices,
        showLabelsOnSlices,
        valueLabelMinPercent,
        valueFormatter,
    ])

    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!layout || isPinned) {
                return
            }
            const rect = e.currentTarget.getBoundingClientRect()
            const x = e.clientX - rect.left
            const y = e.clientY - rect.top
            const index = hitTestSlice(x, y, layout, sliceAngles)
            setHoverIndex(index)
            setHoverPosition(index >= 0 ? { x, y } : null)
        },
        [layout, sliceAngles, isPinned]
    )

    const onMouseLeave = useCallback(() => {
        if (isPinned) {
            return
        }
        clearHover()
    }, [isPinned, clearHover])

    const onClick = useCallback(() => {
        const currentIndex = hoverIndexRef.current
        if (currentIndex < 0) {
            return
        }
        if (isPinned) {
            clearHover()
            return
        }
        // Pinning and onSliceClick are independent — a consumer can ask for both, in which
        // case the click pins the tooltip *and* fires the callback. We don't early-return
        // here so the two paths don't shadow each other.
        if (pinnableTooltip && showTooltip) {
            setIsPinned(true)
        }
        if (onSliceClick) {
            const slice = visibleSlices[currentIndex]
            onSliceClick({
                sliceIndex: currentIndex,
                slice,
                value: slice.value,
                percent: total > 0 ? (slice.value / total) * 100 : 0,
                total,
            })
        }
    }, [isPinned, pinnableTooltip, showTooltip, clearHover, onSliceClick, visibleSlices, total])

    // Dismiss pinned tooltip via Escape or outside click — same UX as the bar/line tooltip.
    useEffect(() => {
        if (!isPinned) {
            return
        }
        const handleClickOutside = (e: MouseEvent): void => {
            const target = e.target
            if (target instanceof Element && target.closest('[data-hog-charts-tooltip]')) {
                return
            }
            const wrapper = wrapperRef.current
            if (wrapper && !wrapper.contains(target as Node)) {
                clearHover()
            }
        }
        const handleKeyDown = (e: KeyboardEvent): void => {
            if (e.key === 'Escape') {
                clearHover()
            }
        }
        const timer = setTimeout(() => {
            document.addEventListener('click', handleClickOutside, { passive: true })
        }, 0)
        document.addEventListener('keydown', handleKeyDown, { passive: true })
        return () => {
            clearTimeout(timer)
            document.removeEventListener('click', handleClickOutside)
            document.removeEventListener('keydown', handleKeyDown)
        }
    }, [isPinned, wrapperRef, clearHover])

    const canvasBounds = useCallback(
        (): DOMRect => canvasRef.current?.getBoundingClientRect() ?? new DOMRect(),
        [canvasRef]
    )

    // Each slice becomes a single-point synthetic Series so the tooltip context matches
    // the bar/line shape — the testing harness, DefaultTooltip, and `TooltipSnapshot.series`
    // accessor all key off `series.key`, which mirrors `slice.key` here.
    const seriesData = useMemo(
        () =>
            visibleSlices.map((slice) => {
                const series: Series<Meta> = {
                    key: slice.key,
                    label: slice.label,
                    data: [slice.value],
                    color: slice.color,
                    meta: slice.meta,
                }
                return { series, value: slice.value, color: slice.color }
            }),
        [visibleSlices]
    )

    const tooltipCtx = useMemo<TooltipContext<Meta> | null>(() => {
        if (!showTooltip || hoverIndex < 0 || !hoverPosition) {
            return null
        }
        const slice = visibleSlices[hoverIndex]
        if (!slice) {
            return null
        }
        return {
            dataIndex: hoverIndex,
            label: slice.label,
            seriesData,
            position: hoverPosition,
            hoverPosition,
            canvasBounds: canvasBounds(),
            isPinned,
            onUnpin: isPinned ? unpin : undefined,
        }
    }, [showTooltip, hoverIndex, hoverPosition, visibleSlices, seriesData, canvasBounds, isPinned, unpin])

    const wrapperStyle =
        hoverIndex >= 0 && (onSliceClick || pinnableTooltip) ? WRAPPER_STYLE_POINTER : WRAPPER_STYLE_DEFAULT

    const ariaLabel = `Chart with ${visibleSlices.length} data series`

    if (visibleSlices.length === 0) {
        const fallback = emptyState ?? <span style={{ fontSize: 13, opacity: 0.6 }}>No data to display</span>
        return (
            <div
                ref={wrapperRef}
                className={className}
                data-attr={dataAttr}
                style={WRAPPER_STYLE_DEFAULT}
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
        <div
            ref={wrapperRef}
            className={className}
            data-attr={dataAttr}
            style={wrapperStyle}
            onMouseMove={onMouseMove}
            onMouseLeave={onMouseLeave}
            onClick={onClick}
        >
            <canvas ref={canvasRef} role="img" aria-label={ariaLabel} style={CANVAS_STYLE} />
            {tooltipCtx && (
                <PiePortalTooltip ctx={tooltipCtx} theme={theme}>
                    {tooltipRenderProp ? (
                        tooltipRenderProp(tooltipCtx)
                    ) : (
                        <PieTooltip ctx={tooltipCtx} theme={theme} valueFormatter={valueFormatter} />
                    )}
                </PiePortalTooltip>
            )}
        </div>
    )
}

interface PiePortalTooltipProps<Meta> {
    ctx: TooltipContext<Meta>
    theme: ChartTheme
    children: React.ReactNode
}

function PiePortalTooltip<Meta>({ ctx, theme, children }: PiePortalTooltipProps<Meta>): React.ReactElement {
    const zIndex = theme.tooltipZIndex ?? DEFAULT_TOOLTIP_Z_INDEX
    const x = ctx.canvasBounds.left + ctx.position.x
    const y = ctx.canvasBounds.top + ctx.position.y

    const virtualReference = useMemo<VirtualElement>(
        () => ({
            getBoundingClientRect: () => ({
                x,
                y,
                width: 0,
                height: 0,
                top: y,
                right: x,
                bottom: y,
                left: x,
            }),
        }),
        [x, y]
    )

    const { refs, floatingStyles } = useFloating({
        placement: 'right',
        strategy: 'fixed',
        middleware: TOOLTIP_MIDDLEWARE,
    })

    useLayoutEffect(() => {
        refs.setPositionReference(virtualReference)
    }, [virtualReference, refs])

    return (
        <FloatingPortal>
            <div
                ref={refs.setFloating}
                data-hog-charts-tooltip=""
                className={ctx.isPinned ? 'hog-charts-tooltip--pinned' : undefined}
                // eslint-disable-next-line react/forbid-dom-props
                style={{
                    ...floatingStyles,
                    pointerEvents: ctx.isPinned ? 'auto' : 'none',
                    width: 'max-content',
                    zIndex,
                }}
            >
                {children}
            </div>
        </FloatingPortal>
    )
}
