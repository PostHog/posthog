import React, { useCallback, useLayoutEffect, useMemo, useState } from 'react'

import { ChartHoverContext, ChartLayoutContext } from '../../core/chart-context'
import type { ChartHoverContextValue, ChartLayoutContextValue } from '../../core/chart-context'
import { ChartShell, useCanvasBounds } from '../../core/chart-shell'
import { ChartErrorBoundary } from '../../core/ChartErrorBoundary'
import { useAnimatedNumber } from '../../core/hooks/useAnimatedNumber'
import { useChartCanvas } from '../../core/hooks/useChartCanvas'
import { useChartDraw } from '../../core/hooks/useChartDraw'
import { useResolvedChartTheme } from '../../core/theme'
import type { ChartDrawArgs, ChartMargins, ChartScales, ChartTheme, TooltipContext } from '../../core/types'
import { defaultResolveValue } from '../../core/types'
import { Tooltip } from '../../overlays/Tooltip'
import { measureLabelWidth } from '../../utils/text-measure'
import { drawGauge } from './draw-gauge'
import type { GaugePaint } from './draw-gauge'
import { initialGaugeColors, resolveGaugeColors } from './gauge-colors'
import {
    clampGaugeSweep,
    computeGaugeLayout,
    DEFAULT_GAUGE_THICKNESS,
    fractionToAngle,
    GAUGE_VALUE_FONT_WEIGHT,
    gaugeFraction,
    isOverGauge,
    layoutGaugeText,
    resolveGaugeBounds,
    sortThresholds,
    thresholdBands,
    thresholdIndexAt,
} from './gauge-layout'
import type { GaugeLayout, GaugeThreshold } from './gauge-layout'
import { GAUGE_EMPTY_VALUE, GaugeTooltip } from './GaugeTooltip'
import type { GaugeTooltipContext, GaugeTooltipThreshold } from './GaugeTooltip'

export interface GaugeTarget {
    /** Where the tick sits, in the same units as `value`. */
    value: number
    /** Names the target in the tooltip, such as `'SLO'`. Defaults to `'Target'`. */
    label?: string
}

export interface GaugeConfig {
    /** Degrees the arc spans, centered on 12 o'clock. Default 240. Clamped to 180 (a half circle)
     *  through 360 (a full ring). */
    sweepAngle?: number
    /** Arc thickness as a fraction of the gauge radius, so it scales with the container, up to 28px.
     *  Default 0.15. */
    thickness?: number
    /** Formats the value, the min and max labels, and the tooltip. `buildYTickFormatter` builds one from
     *  the axis format options (`duration`, `percentage`, `currency`, prefixes and suffixes). */
    valueFormatter?: (value: number) => string
    /** Show the min and max under the arc ends. Default true. Always hidden above a 300° sweep, where
     *  the ends meet, and when the two labels would overlap. */
    showMinMax?: boolean
    /** Draw the threshold bands as a thin ring outside the track. Default true when there are two or
     *  more thresholds. */
    showThresholdBands?: boolean
    /** Track color. Defaults to a faint tint of the page text color. */
    trackColor?: string
    /** Duration (ms) of the value arc's ease to a new value. Default 500. `0` snaps. Reduced motion
     *  always snaps. */
    animationMs?: number
    tooltip?: {
        /** Show the tooltip on hover. Default true. */
        enabled?: boolean
    }
}

export interface GaugeProps {
    /** The value to show. `null` draws an empty track and a dash, not a zero. */
    value: number | null
    /** Range start. Defaults to the lowest threshold, else 0. A value or target below that widens the
     *  range down to 0, or to the value when it is negative. */
    min?: number
    /** Range end. Defaults to the highest threshold, else the larger of `min + 1` and 0, raised to
     *  contain the value and the target. Out-of-range values still print as-is and the arc clamps to
     *  the end. */
    max?: number
    /** Color steps. The arc takes the color of the step the value falls in, and the steps draw as
     *  bands around the track. Order does not matter. Colors may be `var(--…)`. */
    thresholds?: readonly GaugeThreshold[]
    /** Arc color without thresholds: hex, rgb, or `var(--…)`. Defaults to `theme.colors[0]`. */
    color?: string
    /** Palette and chrome colors. Defaults to the nearest `ChartThemeProvider`, then the quill CSS vars.
     *  A new theme object, as on a light or dark switch, resolves every `var(--…)` color again. */
    theme?: ChartTheme
    /** Short caption under the value, such as the metric name. Truncates to fit the arc. */
    label?: string
    /** Marks a value on the track with a tick, such as an SLO target. Hidden when outside the range. */
    target?: number | GaugeTarget
    /** Shape, formatting, animation, and tooltip options. */
    config?: GaugeConfig
    /** Replaces the default tooltip content. */
    tooltip?: (ctx: GaugeTooltipContext) => React.ReactNode
    /** Classes for the chart wrapper. */
    className?: string
    /** `data-attr` applied to the chart wrapper. */
    dataAttr?: string
    /** Called when rendering throws. The gauge then renders a fallback instead of unmounting its parent. */
    onError?: (error: Error, info: React.ErrorInfo) => void
}

const ZERO_MARGINS: ChartMargins = { top: 0, right: 0, bottom: 0, left: 0 }
const PADDING = 4
const DEFAULT_ANIMATION_MS = 500
const MAX_MINMAX_SWEEP = 300
const EMPTY_SERIES: never[] = []
const EMPTY_LABELS: string[] = []
// Where the tooltip anchors, as a fraction of the outer radius up and right of the center: the
// top-right shoulder of the ring, so it sits beside the gauge instead of over the value.
const TOOLTIP_ANCHOR = 0.72

const TEXT_BASE_STYLE: React.CSSProperties = {
    position: 'absolute',
    transform: 'translate(-50%, -50%)',
    whiteSpace: 'nowrap',
    overflow: 'hidden',
    textOverflow: 'ellipsis',
    lineHeight: 1.2,
    textAlign: 'center',
    pointerEvents: 'none',
}

const MUTED_STYLE: React.CSSProperties = { opacity: 0.65 }

export function Gauge({ onError, ...rest }: GaugeProps): React.ReactElement {
    return (
        <ChartErrorBoundary onError={onError}>
            <GaugeInner {...rest} />
        </ChartErrorBoundary>
    )
}

function defaultFormatter(value: number): string {
    return value.toLocaleString('en-US', { maximumFractionDigits: 2 })
}

function paintFromScales(scales: ChartScales): GaugePaint | null {
    return (scales._private as { gauge?: GaugePaint } | undefined)?.gauge ?? null
}

function drawStatic({ ctx, scales }: ChartDrawArgs): void {
    const paint = paintFromScales(scales)
    if (paint) {
        drawGauge(ctx, paint)
    }
}

function drawHover(): boolean {
    return false
}

function minMaxFontSize(width: number, height: number): number {
    return Math.min(13, Math.max(9, Math.min(width, height * 1.3) * 0.045))
}

interface MinMaxLabel {
    text: string
    x: number
}

function placeMinMax(
    layout: GaugeLayout,
    width: number,
    minText: string,
    maxText: string,
    font: string
): [MinMaxLabel, MinMaxLabel] | null {
    const { cx, radius, angles } = layout
    const minWidth = measureLabelWidth(minText, font)
    const maxWidth = measureLabelWidth(maxText, font)
    const edge = 2
    const minX = Math.min(Math.max(cx + Math.cos(angles.start) * radius, edge + minWidth / 2), width - edge)
    const maxX = Math.max(Math.min(cx + Math.cos(angles.end) * radius, width - edge - maxWidth / 2), edge)
    if (minX + minWidth / 2 + 6 > maxX - maxWidth / 2) {
        return null
    }
    return [
        { text: minText, x: minX },
        { text: maxText, x: maxX },
    ]
}

function GaugeInner({
    value: rawValue,
    min,
    max,
    thresholds,
    color,
    theme: themeProp,
    label,
    target: rawTarget,
    config,
    tooltip,
    className,
    dataAttr,
}: Omit<GaugeProps, 'onError'>): React.ReactElement {
    const theme = useResolvedChartTheme(themeProp)
    const {
        sweepAngle,
        thickness = DEFAULT_GAUGE_THICKNESS,
        valueFormatter,
        showMinMax = true,
        showThresholdBands,
        trackColor: trackColorProp,
        animationMs: rawAnimationMs,
        tooltip: tooltipConfig,
    } = config ?? {}
    const animationMs =
        rawAnimationMs !== undefined && Number.isFinite(rawAnimationMs) ? rawAnimationMs : DEFAULT_ANIMATION_MS
    const sweep = clampGaugeSweep(sweepAngle)
    const value = rawValue !== null && Number.isFinite(rawValue) ? rawValue : null
    const targetValue = typeof rawTarget === 'number' ? rawTarget : rawTarget?.value
    const targetLabel = typeof rawTarget === 'number' ? undefined : rawTarget?.label
    // Keyed on the fields, so an inline `target={{ … }}` does not repaint the canvas on every render.
    const target = useMemo<GaugeTarget | null>(
        () =>
            targetValue !== undefined && Number.isFinite(targetValue)
                ? { value: targetValue, label: targetLabel }
                : null,
        [targetValue, targetLabel]
    )

    const { canvasRef, overlayCanvasRef, wrapperRef, dimensions, ctx, overlayCtx } = useChartCanvas({
        margins: ZERO_MARGINS,
    })

    const formatValue = valueFormatter ?? defaultFormatter

    // Keyed on the content, so an inline `thresholds={[…]}` does not re-resolve colors and repaint the
    // canvas on every parent render. A threshold list is a handful of steps, so the key is cheap.
    const thresholdsKey = (thresholds ?? [])
        .map((t) => `${t.value}\u0000${t.color}\u0000${t.label ?? ''}`)
        .join('\u0001')
    // eslint-disable-next-line react-hooks/exhaustive-deps
    const sorted = useMemo(() => sortThresholds(thresholds), [thresholdsKey])
    const bounds = useMemo(
        () => resolveGaugeBounds({ value, min, max, thresholds: sorted, target: target?.value }),
        [value, min, max, sorted, target]
    )

    // Computed styles are read in a layout effect, not during render, and again on every theme change,
    // because a light/dark flip changes what each `var(--…)` means while the input string stays the same.
    const [colors, setColors] = useState(() => initialGaugeColors({ sorted, color, trackColor: trackColorProp, theme }))
    useLayoutEffect(() => {
        const root = wrapperRef.current
        if (root) {
            setColors(resolveGaugeColors(root, { sorted, color, trackColor: trackColorProp, theme }))
        }
    }, [wrapperRef, sorted, color, trackColorProp, theme])
    const { base: baseColor, thresholds: resolvedThresholds, track: trackColor, ink, fontFamily } = colors

    const targetFraction = value === null ? 0 : gaugeFraction(value, bounds)
    const animatedFraction = useAnimatedNumber(targetFraction, animationMs)
    const settled = animatedFraction === targetFraction
    const colorValue = settled ? value : bounds.min + animatedFraction * (bounds.max - bounds.min)
    const valueIndex = thresholdIndexAt(value, resolvedThresholds)
    const arcIndex = thresholdIndexAt(colorValue, resolvedThresholds)
    const arcColor = arcIndex >= 0 ? resolvedThresholds[arcIndex].color : baseColor
    const valueColor = valueIndex >= 0 ? resolvedThresholds[valueIndex].color : baseColor

    const bandsVisible = showThresholdBands ?? resolvedThresholds.length > 1
    const showEnds = showMinMax && sweep <= MAX_MINMAX_SWEEP
    const minMaxFont = dimensions ? minMaxFontSize(dimensions.width, dimensions.height) : 0
    const minText = formatValue(bounds.min)
    const maxText = formatValue(bounds.max)
    const hasTarget = target !== null

    const { layout, ends } = useMemo<{ layout: GaugeLayout | null; ends: [MinMaxLabel, MinMaxLabel] | null }>(() => {
        if (!dimensions) {
            return { layout: null, ends: null }
        }
        const fit = (footer: number): GaugeLayout =>
            computeGaugeLayout({
                width: dimensions.width,
                height: dimensions.height,
                sweep,
                thickness,
                showBands: bandsVisible && resolvedThresholds.length > 0,
                footer,
                padding: PADDING,
                hasTarget,
            })
        if (!showEnds) {
            return { layout: fit(0), ends: null }
        }
        const withFooter = fit(minMaxFont * 1.6)
        const placed = placeMinMax(withFooter, dimensions.width, minText, maxText, `${minMaxFont}px ${fontFamily}`)
        // Labels that would overlap stay hidden, so the rings take back the room reserved for them.
        return placed ? { layout: withFooter, ends: placed } : { layout: fit(0), ends: null }
    }, [
        dimensions,
        sweep,
        thickness,
        bandsVisible,
        resolvedThresholds.length,
        hasTarget,
        showEnds,
        minMaxFont,
        minText,
        maxText,
        fontFamily,
    ])

    const bandPaint = useMemo(() => {
        if (!layout || !bandsVisible) {
            return []
        }
        return thresholdBands(resolvedThresholds, bounds).map((band) => ({
            startAngle: fractionToAngle(gaugeFraction(band.from, bounds), layout.angles),
            endAngle: fractionToAngle(gaugeFraction(band.to, bounds), layout.angles),
            color: band.threshold.color,
        }))
    }, [layout, bandsVisible, resolvedThresholds, bounds])

    const paint = useMemo<GaugePaint | null>(() => {
        if (!layout) {
            return null
        }
        const targetInRange = target !== null && target.value >= bounds.min && target.value <= bounds.max
        return {
            layout,
            trackColor,
            bands: bandPaint,
            valueAngle: animatedFraction > 0 ? fractionToAngle(animatedFraction, layout.angles) : null,
            valueColor: arcColor,
            targetAngle:
                targetInRange && target ? fractionToAngle(gaugeFraction(target.value, bounds), layout.angles) : null,
            targetColor: ink,
        }
    }, [layout, trackColor, bandPaint, animatedFraction, arcColor, target, bounds, ink])

    // The paint rides on `scales._private`, so the draw functions stay module-level and each frame of
    // the value animation reaches the canvas through the same input the draw loop already watches.
    const scales = useMemo<ChartScales | null>(
        () => (paint ? { x: () => undefined, y: () => 0, yTicks: () => [], _private: { gauge: paint } } : null),
        [paint]
    )

    useChartDraw({
        ctx,
        overlayCtx,
        dimensions,
        scales,
        series: EMPTY_SERIES,
        labels: EMPTY_LABELS,
        hoverIndex: -1,
        hoverPosition: null,
        theme,
        drawStatic,
        drawHover,
    })

    const valueText = value === null ? GAUGE_EMPTY_VALUE : formatValue(value)

    const text = useMemo(() => {
        if (!layout || layout.innerRadius <= 0) {
            return null
        }
        return layoutGaugeText({
            layout,
            measure: measureLabelWidth,
            fontFamily: fontFamily,
            valueText,
            labelText: label || null,
        })
    }, [layout, fontFamily, valueText, label])

    const tooltipThreshold = useMemo<GaugeTooltipThreshold | null>(() => {
        if (valueIndex < 0) {
            return null
        }
        return {
            index: valueIndex,
            threshold: resolvedThresholds[valueIndex],
            from: valueIndex === 0 ? undefined : resolvedThresholds[valueIndex].value,
            to: valueIndex + 1 < resolvedThresholds.length ? resolvedThresholds[valueIndex + 1].value : undefined,
        }
    }, [valueIndex, resolvedThresholds])

    const canvasBounds = useCanvasBounds(canvasRef)
    // The wrapper's rect while the cursor is over the ring, or null when it is outside.
    const [hoverRect, setHoverRect] = useState<DOMRect | null>(null)
    const showTooltip = tooltipConfig?.enabled !== false

    // The tooltip anchors to the gauge, not the cursor. While the cursor stays over the ring and the
    // gauge does not move, the state update returns the previous rect, so React bails out and nothing
    // re-renders or redraws. A scroll moves the rect, so the tooltip follows.
    const onMouseMove = useCallback(
        (e: React.MouseEvent<HTMLDivElement>) => {
            if (!layout || !showTooltip) {
                return
            }
            const rect = e.currentTarget.getBoundingClientRect()
            const hit = isOverGauge(layout, e.clientX - rect.left, e.clientY - rect.top)
            setHoverRect((previous) =>
                !hit ? null : previous && previous.left === rect.left && previous.top === rect.top ? previous : rect
            )
        },
        [layout, showTooltip]
    )
    const onMouseLeave = useCallback(() => setHoverRect(null), [])
    const handlers = useMemo(() => ({ onMouseMove, onMouseLeave, onClick: () => {} }), [onMouseMove, onMouseLeave])

    // One object goes to `<Tooltip>` and to the render prop, so `renderChart` captures what a custom
    // tooltip receives.
    const tooltipCtx = useMemo<GaugeTooltipContext | null>(() => {
        if (!hoverRect || !layout) {
            return null
        }
        return {
            dataIndex: 0,
            label: label ?? '',
            seriesData: [],
            position: {
                x: layout.cx + layout.outerRadius * TOOLTIP_ANCHOR,
                y: layout.cy - layout.outerRadius * TOOLTIP_ANCHOR,
            },
            hoverPosition: null,
            canvasBounds: hoverRect,
            isPinned: false,
            value,
            min: bounds.min,
            max: bounds.max,
            threshold: tooltipThreshold,
            thresholdCount: resolvedThresholds.length,
            target,
            color: valueColor,
            formatValue,
        }
    }, [hoverRect, layout, label, value, bounds, tooltipThreshold, resolvedThresholds, target, valueColor, formatValue])

    const renderTooltip = useCallback(
        (ctx: TooltipContext): React.ReactNode => {
            const gaugeCtx = ctx as GaugeTooltipContext
            return tooltip ? tooltip(gaugeCtx) : <GaugeTooltip ctx={gaugeCtx} />
        },
        [tooltip]
    )

    const layoutValue = useMemo<ChartLayoutContextValue | null>(() => {
        if (!scales || !dimensions) {
            return null
        }
        return {
            scales,
            dimensions,
            labels: EMPTY_LABELS,
            series: EMPTY_SERIES,
            theme,
            resolvePositionValue: defaultResolveValue,
            canvasBounds,
            axis: { orientation: 'vertical', xTickFormatter: undefined, isPercent: false },
            yGutters: [],
        }
    }, [scales, dimensions, theme, canvasBounds])
    const hovered = hoverRect !== null
    const hoverValue = useMemo<ChartHoverContextValue>(() => ({ hoverIndex: hovered ? 0 : -1 }), [hovered])

    const ariaLabel = [
        label ? `${label}:` : 'Gauge:',
        valueText === GAUGE_EMPTY_VALUE ? 'no data' : valueText,
        `of ${minText} to ${maxText}`,
        tooltipThreshold?.threshold.label ? `(${tooltipThreshold.threshold.label})` : '',
    ]
        .filter(Boolean)
        .join(' ')

    const labelColor = theme.axisColor
    return (
        <ChartLayoutContext.Provider value={layoutValue}>
            <ChartHoverContext.Provider value={hoverValue}>
                <ChartShell
                    wrapperRef={wrapperRef}
                    canvasRef={canvasRef}
                    overlayCanvasRef={overlayCanvasRef}
                    className={className}
                    dataAttr={dataAttr}
                    pointer={false}
                    ariaLabel={ariaLabel}
                    handlers={handlers}
                    showOverlay={!!layout}
                >
                    {text ? (
                        <>
                            <div
                                aria-hidden="true"
                                data-attr="hog-chart-gauge-value"
                                title={text.value.text}
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{
                                    ...TEXT_BASE_STYLE,
                                    left: text.value.x,
                                    top: text.value.y,
                                    maxWidth: text.value.maxWidth,
                                    fontSize: text.value.fontSize,
                                    fontWeight: value === null ? 400 : GAUGE_VALUE_FONT_WEIGHT,
                                    lineHeight: 1.1,
                                    ...(value === null
                                        ? labelColor
                                            ? { color: labelColor }
                                            : MUTED_STYLE
                                        : { color: valueColor }),
                                }}
                            >
                                {text.value.text}
                            </div>
                            {text.label ? (
                                <div
                                    aria-hidden="true"
                                    data-attr="hog-chart-gauge-label"
                                    title={text.label.text}
                                    // eslint-disable-next-line react/forbid-dom-props
                                    style={{
                                        ...TEXT_BASE_STYLE,
                                        ...(labelColor ? { color: labelColor } : MUTED_STYLE),
                                        left: text.label.x,
                                        top: text.label.y,
                                        maxWidth: text.label.maxWidth,
                                        fontSize: text.label.fontSize,
                                    }}
                                >
                                    {text.label.text}
                                </div>
                            ) : null}
                        </>
                    ) : null}
                    {ends && layout
                        ? ends.map((end, i) => (
                              <div
                                  key={i}
                                  aria-hidden="true"
                                  data-attr={i === 0 ? 'hog-chart-gauge-min' : 'hog-chart-gauge-max'}
                                  // eslint-disable-next-line react/forbid-dom-props
                                  style={{
                                      ...TEXT_BASE_STYLE,
                                      ...(labelColor ? { color: labelColor } : MUTED_STYLE),
                                      transform: 'translate(-50%, 0)',
                                      left: end.x,
                                      top: layout.bottom + minMaxFont * 0.3,
                                      fontSize: minMaxFont,
                                      fontVariantNumeric: 'tabular-nums',
                                  }}
                              >
                                  {end.text}
                              </div>
                          ))
                        : null}
                    {tooltipCtx && showTooltip ? (
                        <Tooltip context={tooltipCtx} renderTooltip={renderTooltip} placement="follow-data" />
                    ) : null}
                </ChartShell>
            </ChartHoverContext.Provider>
        </ChartLayoutContext.Provider>
    )
}
