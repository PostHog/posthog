import React, { useMemo } from 'react'

import { useChartHover, useChartLayout } from '../core/chart-context'
import { barColorAt } from '../core/color-utils'
import { resolveYScaleForSeries } from '../core/scales'
import type { ChartDimensions, ChartScales, ResolvedSeries, ResolveValueFn } from '../core/types'
import { getTextMeasureCtx } from '../utils/text-measure'

export type ValueLabelsMode = 'per-segment' | 'stack-total'

/** Per-segment context handed to a value formatter so callers can compute labels that depend on
 *  the band (e.g. each segment's share of its band). Keeps band/stacking knowledge in the library
 *  while leaving the label text — values, percentages, units — entirely to the caller. */
export interface ValueLabelContext {
    /** Underlying value of this segment (the band total for stack-total labels). In percent layout
     *  the formatter's `value` arg is the segment's fraction (0..1); `rawValue` stays the original so
     *  callers can compute their own shares. */
    rawValue: number
    /** Finite values of every series contributing to this band's stack (non-excluded, not a fill
     *  lower-bound, not an overlay) at this dataIndex — the denominator set for share math. */
    bandValues: number[]
    /** Same as `bandValues` for the preceding dataIndex; empty at the first index. */
    previousBandValues: number[]
    /** True in normalized/percent layout, where `value` is already a fraction. */
    isPercent: boolean
}

/** Returning an empty string skips the label entirely. */
export type ValueLabelFormatter = (
    value: number,
    /** `-1` for stack-total labels. */
    seriesIndex: number,
    dataIndex: number,
    context: ValueLabelContext
) => string

export interface ValueLabelsProps {
    valueFormatter?: ValueLabelFormatter
    minGap?: number
    mode?: ValueLabelsMode
    /** Gap in px between the bar tip and the label, applied along the value axis in the outward
     *  direction (right/above the tip, or inward for labels flipped inside a clipped bar). Ignored
     *  for centered (`percent`) labels. Defaults to 0 — the label's edge sits on the bar tip. */
    offset?: number
}

const LABEL_FONT =
    '600 12px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'
const LABEL_HEIGHT = 22
const LABEL_PADDING_X = 4
const LABEL_BORDER = 2
const LABEL_HORIZONTAL_CHROME = (LABEL_PADDING_X + LABEL_BORDER) * 2
const STACK_TOTAL_KEY = '__stack_total__'

interface Candidate {
    key: string
    seriesIndex: number
    /** Matched against `hoverIndex` so the hovered candidate can lift. */
    dataIndex: number
    text: string
    x: number
    y: number
    width: number
    color: string
    above: boolean
    /** Center the label across the value-axis coord instead of anchoring its leading edge there. */
    centerAnchor: boolean
}

const HOVER_LIFT_PX = 6

function defaultLocaleFormatter(v: number): string {
    return v.toLocaleString()
}

interface BuildCandidatesArgs {
    series: ResolvedSeries[]
    labels: string[]
    scales: ChartScales
    resolvePositionValue: ResolveValueFn
    valueFormatter: NonNullable<ValueLabelsProps['valueFormatter']>
    isHorizontal: boolean
    mode: ValueLabelsMode
    isPercent: boolean
}

function pushCandidate(
    out: Candidate[],
    ctx: CanvasRenderingContext2D | null,
    isHorizontal: boolean,
    key: string,
    seriesIndex: number,
    dataIndex: number,
    color: string,
    text: string,
    categoricalCoord: number,
    valueCoord: number,
    above: boolean,
    centerAnchor: boolean = false
): void {
    const textWidth = ctx ? ctx.measureText(text).width : text.length * 6
    const width = textWidth + LABEL_HORIZONTAL_CHROME
    out.push({
        key,
        seriesIndex,
        dataIndex,
        text,
        x: isHorizontal ? valueCoord : categoricalCoord,
        y: isHorizontal ? categoricalCoord : valueCoord,
        width,
        color,
        above,
        centerAnchor,
    })
}

function buildCandidates(args: BuildCandidatesArgs): Candidate[] {
    const ctx = getTextMeasureCtx()
    if (ctx) {
        ctx.font = LABEL_FONT
    }
    return args.mode === 'stack-total' ? buildStackTotal(args, ctx) : buildPerSegment(args, ctx)
}

function stackContributors(series: ResolvedSeries[]): ResolvedSeries[] {
    return series.filter((s) => !s.visibility?.excluded && !s.fill?.lowerData && !s.overlay)
}

function bandValuesAt(contributors: ResolvedSeries[], dIdx: number): number[] {
    const values: number[] = []
    for (const s of contributors) {
        const v = s.data[dIdx]
        if (typeof v === 'number' && isFinite(v)) {
            values.push(v)
        }
    }
    return values
}

function bandTotal(visible: ResolvedSeries[], dIdx: number): number | null {
    let total = 0
    let count = 0
    let hasPositive = false
    let hasNegative = false
    for (const s of visible) {
        const v = s.data[dIdx]
        if (typeof v === 'number' && isFinite(v)) {
            total += v
            count++
            if (v > 0) {
                hasPositive = true
            } else if (v < 0) {
                hasNegative = true
            }
        }
    }
    if (count === 0 || total === 0 || !isFinite(total) || (hasPositive && hasNegative)) {
        return null
    }
    return total
}

function buildStackTotal(args: BuildCandidatesArgs, ctx: CanvasRenderingContext2D | null): Candidate[] {
    const { series, labels, scales, valueFormatter, isHorizontal, isPercent } = args
    const out: Candidate[] = []
    if (isPercent) {
        return out
    }
    const visible = series.filter((s) => !s.visibility?.excluded && s.visibility?.valueLabel !== false)
    if (visible.length === 0) {
        return out
    }
    const topSeries = visible[visible.length - 1]
    const yScale = resolveYScaleForSeries(scales, topSeries)

    for (let dIdx = 0; dIdx < labels.length; dIdx++) {
        const total = bandTotal(visible, dIdx)
        if (total === null) {
            continue
        }
        const categoricalCoord = scales.x(labels[dIdx])
        const valueCoord = yScale(total)
        if (categoricalCoord == null || !isFinite(categoricalCoord) || !isFinite(valueCoord)) {
            continue
        }
        // `visible` (label-eligible series) rather than all stack contributors, so `bandValues`
        // sums to the `total` shown — `buildPerSegment` deliberately uses the wider contributor set.
        const text = valueFormatter(total, -1, dIdx, {
            rawValue: total,
            bandValues: bandValuesAt(visible, dIdx),
            previousBandValues: dIdx > 0 ? bandValuesAt(visible, dIdx - 1) : [],
            isPercent,
        })
        if (text === '') {
            continue
        }
        pushCandidate(
            out,
            ctx,
            isHorizontal,
            `${STACK_TOTAL_KEY}-${dIdx}`,
            -1,
            dIdx,
            barColorAt(topSeries, dIdx),
            text,
            categoricalCoord,
            valueCoord,
            total >= 0
        )
    }
    return out
}

function buildPerSegment(args: BuildCandidatesArgs, ctx: CanvasRenderingContext2D | null): Candidate[] {
    const { series, labels, scales, resolvePositionValue, valueFormatter, isHorizontal, isPercent } = args
    const out: Candidate[] = []

    // Stack denominator — for percent-layout fraction placement and for the `bandValues` handed to
    // the formatter. Includes `valueLabel: false` series, which still contribute to stack height.
    // The band depends only on `dIdx`, so compute it once per index instead of per segment.
    const contributors = stackContributors(series)
    const bandValuesByIndex = labels.map((_, dIdx) => bandValuesAt(contributors, dIdx))
    const bandTotalByIndex = isPercent ? labels.map((_, dIdx) => bandTotal(contributors, dIdx)) : []

    for (let sIdx = 0; sIdx < series.length; sIdx++) {
        const s = series[sIdx]
        if (s.visibility?.excluded || s.visibility?.valueLabel === false) {
            continue
        }
        const yScale = resolveYScaleForSeries(scales, s)
        for (let dIdx = 0; dIdx < s.data.length && dIdx < labels.length; dIdx++) {
            const rawValue = s.data[dIdx]
            if (typeof rawValue !== 'number' || !isFinite(rawValue) || rawValue === 0) {
                continue
            }
            const yValue = resolvePositionValue(s, dIdx)
            if (typeof yValue !== 'number' || !isFinite(yValue)) {
                continue
            }

            let displayValue = rawValue
            // In percent layout we center the label across the segment's stacked top (see
            // `centerAnchor` below), so `above` is unused — keep it false to be explicit.
            let above = isPercent ? false : yValue >= 0

            if (isPercent) {
                const total = bandTotalByIndex[dIdx]
                if (total == null || total === 0) {
                    continue
                }
                // Pass the fraction (0..1) so consumers can use the same percentage formatter
                // (`percentage_scaled`, BarChart's default tick formatter, etc.) they already use
                // for the value axis.
                displayValue = rawValue / total
            }

            // Pass `s.key` so grouped bar charts (compare-against-previous) anchor each
            // label on its own bar rather than the band center between bars. Other chart
            // types ignore the second arg and fall back to the band/point center.
            const categoricalCoord = scales.x(labels[dIdx], s.key)
            const valueCoord = yScale(yValue)
            if (categoricalCoord == null || !isFinite(categoricalCoord) || !isFinite(valueCoord)) {
                continue
            }
            const text = valueFormatter(displayValue, sIdx, dIdx, {
                rawValue,
                bandValues: bandValuesByIndex[dIdx],
                previousBandValues: dIdx > 0 ? bandValuesByIndex[dIdx - 1] : [],
                isPercent,
            })
            if (text === '') {
                continue
            }

            pushCandidate(
                out,
                ctx,
                isHorizontal,
                `${s.key}-${dIdx}`,
                sIdx,
                dIdx,
                barColorAt(s, dIdx),
                text,
                categoricalCoord,
                valueCoord,
                above,
                isPercent
            )
        }
    }
    return out
}

interface Rect {
    left: number
    right: number
    top: number
    bottom: number
}

function labelRect(c: Candidate, isHorizontal: boolean): Rect {
    if (isHorizontal) {
        const halfH = LABEL_HEIGHT / 2
        let left: number
        if (c.centerAnchor) {
            left = c.x - c.width / 2
        } else {
            left = c.above ? c.x : c.x - c.width
        }
        return { left, right: left + c.width, top: c.y - halfH, bottom: c.y + halfH }
    }
    const halfW = c.width / 2
    let top: number
    if (c.centerAnchor) {
        top = c.y - LABEL_HEIGHT / 2
    } else {
        top = c.above ? c.y - LABEL_HEIGHT : c.y
    }
    return { left: c.x - halfW, right: c.x + halfW, top, bottom: top + LABEL_HEIGHT }
}

function rectsOverlap(a: Rect, b: Rect, gap: number): boolean {
    return a.left < b.right + gap && a.right + gap > b.left && a.top < b.bottom + gap && a.bottom + gap > b.top
}

function fitsWithinWrapper(c: Candidate, above: boolean, dimensions: ChartDimensions, isHorizontal: boolean): boolean {
    if (isHorizontal) {
        const left = above ? c.x : c.x - c.width
        return left >= 0 && left + c.width <= dimensions.width
    }
    const top = above ? c.y - LABEL_HEIGHT : c.y
    return top >= 0 && top + LABEL_HEIGHT <= dimensions.height
}

// If the default placement (above/right of the bar) would push the label past the chart
// wrapper edge — which has `overflow: hidden` — flip it inside the bar instead. Avoids
// reserving global plot-area headroom (which would shrink every chart vertically) for a
// case that only hits when a bar reaches the axis top/right. Only flips when the flipped
// position actually fits — if neither side fits, keep the original choice.
function flipClippedCandidates(
    candidates: Candidate[],
    dimensions: ChartDimensions,
    isHorizontal: boolean
): Candidate[] {
    for (const c of candidates) {
        if (c.centerAnchor) {
            continue
        }
        if (fitsWithinWrapper(c, c.above, dimensions, isHorizontal)) {
            continue
        }
        if (fitsWithinWrapper(c, !c.above, dimensions, isHorizontal)) {
            c.above = !c.above
        }
    }
    return candidates
}

function applyCollisionAvoidance(candidates: Candidate[], minGap: number, isHorizontal: boolean): Candidate[] {
    if (candidates.length === 0) {
        return candidates
    }
    const bySeries: Map<number, Candidate[]> = new Map()
    for (const c of candidates) {
        const bucket = bySeries.get(c.seriesIndex)
        if (bucket) {
            bucket.push(c)
        } else {
            bySeries.set(c.seriesIndex, [c])
        }
    }

    const afterPrimary: Candidate[] = []
    for (const group of bySeries.values()) {
        if (isHorizontal) {
            group.sort((a, b) => a.y - b.y)
            const halfH = LABEL_HEIGHT / 2
            let lastBottom = -Infinity
            for (const c of group) {
                if (c.y - halfH >= lastBottom + minGap) {
                    afterPrimary.push(c)
                    lastBottom = c.y + halfH
                }
            }
        } else {
            group.sort((a, b) => a.x - b.x)
            let lastRight = -Infinity
            for (const c of group) {
                const halfW = c.width / 2
                if (c.x - halfW >= lastRight + minGap) {
                    afterPrimary.push(c)
                    lastRight = c.x + halfW
                }
            }
        }
    }

    const visible: Candidate[] = []
    const placedRects: Rect[] = []
    for (const c of afterPrimary) {
        const rect = labelRect(c, isHorizontal)
        if (!placedRects.some((p) => rectsOverlap(rect, p, minGap))) {
            visible.push(c)
            placedRects.push(rect)
        }
    }
    return visible
}

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    // Fixed, even border-box height so `translateY(-50%)` lands on a whole pixel (no half-pixel
    // bias) and the text is flex-centered rather than relying on line-height to centre it.
    boxSizing: 'border-box',
    height: LABEL_HEIGHT,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    color: 'white',
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1,
    padding: `0 ${LABEL_PADDING_X}px`,
    borderRadius: 4,
    borderWidth: LABEL_BORDER,
    borderStyle: 'solid',
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
    transition: 'transform 150ms ease-out',
}

function transformFor(c: Candidate, isHorizontal: boolean, hovered: boolean, offset: number): string {
    // Lift direction depends on which side of the value-axis the label sits on.
    let liftX = 0
    let liftY = 0
    if (hovered) {
        if (c.centerAnchor) {
            liftY = -HOVER_LIFT_PX
        } else if (isHorizontal) {
            liftX = c.above ? HOVER_LIFT_PX : -HOVER_LIFT_PX
        } else {
            liftY = c.above ? -HOVER_LIFT_PX : HOVER_LIFT_PX
        }
    }
    // Nudge the label off the bar tip, away from the baseline (or inward when flipped inside a
    // clipped bar so the gap stays on the bar side). Centered labels sit on the segment, no offset.
    if (offset && !c.centerAnchor) {
        if (isHorizontal) {
            liftX += c.above ? offset : -offset
        } else {
            liftY += c.above ? -offset : offset
        }
    }
    const lift = liftX === 0 && liftY === 0 ? '' : ` translate(${liftX}px, ${liftY}px)`
    if (c.centerAnchor) {
        return `translate(-50%, -50%)${lift}`
    }
    if (isHorizontal) {
        return (c.above ? 'translateY(-50%)' : 'translate(-100%, -50%)') + lift
    }
    return (c.above ? 'translate(-50%, -100%)' : 'translateX(-50%)') + lift
}

export function ValueLabels({
    valueFormatter,
    minGap = 4,
    mode = 'per-segment',
    offset = 0,
}: ValueLabelsProps): React.ReactElement | null {
    const { series, scales, labels, theme, resolvePositionValue, axis, dimensions } = useChartLayout()
    const { hoverIndex } = useChartHover()
    const isHorizontal = axis.orientation === 'horizontal'
    const isPercent = axis.isPercent

    const formatter = valueFormatter ?? defaultLocaleFormatter

    const visible = useMemo(
        () =>
            applyCollisionAvoidance(
                flipClippedCandidates(
                    buildCandidates({
                        series,
                        labels,
                        scales,
                        resolvePositionValue,
                        valueFormatter: formatter,
                        isHorizontal,
                        mode,
                        isPercent,
                    }),
                    dimensions,
                    isHorizontal
                ),
                minGap,
                isHorizontal
            ),
        [series, labels, scales, resolvePositionValue, formatter, minGap, isHorizontal, mode, isPercent, dimensions]
    )

    // Skip the lift when a dataIndex has labels at multiple distinct x positions
    // (grouped bars) — hoverIndex can't disambiguate which bar the cursor is on, so
    // lifting all of them is worse than lifting none. Labels sharing the same x
    // (stacked / multi-series at band center) are one visual column and lift together.
    const liftableIndices = useMemo(() => {
        const xsByIndex = new Map<number, Set<number>>()
        for (const c of visible) {
            const xs = xsByIndex.get(c.dataIndex) ?? new Set<number>()
            xs.add(Math.round(c.x))
            xsByIndex.set(c.dataIndex, xs)
        }
        const set = new Set<number>()
        for (const [dIdx, xs] of xsByIndex) {
            if (xs.size === 1) {
                set.add(dIdx)
            }
        }
        return set
    }, [visible])

    if (visible.length === 0) {
        return null
    }

    const borderColor = theme.backgroundColor ?? 'white'

    return (
        <>
            {visible.map((c) => {
                const isHovered = c.dataIndex === hoverIndex && liftableIndices.has(c.dataIndex)
                return (
                    <div
                        key={c.key}
                        data-attr="hog-chart-value-label"
                        style={{
                            ...LABEL_STYLE_BASE,
                            backgroundColor: c.color,
                            borderColor,
                            left: Math.round(c.x),
                            top: Math.round(c.y),
                            transform: transformFor(c, isHorizontal, isHovered, offset),
                            willChange: isHovered ? 'transform' : undefined,
                        }}
                    >
                        {c.text}
                    </div>
                )
            })}
        </>
    )
}
