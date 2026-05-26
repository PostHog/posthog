import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import { resolveYScaleForSeries } from '../core/scales'
import type { ChartScales, ResolvedSeries, ResolveValueFn } from '../core/types'
import { getTextMeasureCtx } from '../utils/text-measure'

export type ValueLabelsMode = 'per-segment' | 'stack-total'

export interface ValueLabelsProps {
    /** `seriesIndex` is `-1` for stack-total labels. */
    valueFormatter?: (value: number, seriesIndex: number, dataIndex: number) => string
    minGap?: number
    mode?: ValueLabelsMode
}

const LABEL_FONT =
    '600 12px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'
const LABEL_HEIGHT = 22
const LABEL_PADDING_X = 4
const LABEL_PADDING_Y = 2
const LABEL_BORDER = 2
const LABEL_HORIZONTAL_CHROME = (LABEL_PADDING_X + LABEL_BORDER) * 2
const STACK_TOTAL_KEY = '__stack_total__'

interface Candidate {
    key: string
    seriesIndex: number
    text: string
    x: number
    y: number
    width: number
    color: string
    above: boolean
    /** Center the label across the value-axis coord instead of anchoring its leading edge there. */
    centerAnchor: boolean
}

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
    const topColor = topSeries.color

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
        pushCandidate(
            out,
            ctx,
            isHorizontal,
            `${STACK_TOTAL_KEY}-${dIdx}`,
            -1,
            topColor,
            valueFormatter(total, -1, dIdx),
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

    // In percent layout each band sums to 1, so we need the band total to convert each segment's
    // raw value into the fraction d3 uses for placement (`raw / total`). Match the d3 stack's own
    // denominator — every non-excluded stacked series — even if some have `valueLabel: false`,
    // since those still contribute to the visual stack height.
    const visibleForTotal = isPercent
        ? series.filter((s) => !s.visibility?.excluded && !s.fill?.lowerData && !s.overlay)
        : []

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
                const total = bandTotal(visibleForTotal, dIdx)
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
            pushCandidate(
                out,
                ctx,
                isHorizontal,
                `${s.key}-${dIdx}`,
                sIdx,
                s.color,
                valueFormatter(displayValue, sIdx, dIdx),
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
    color: 'white',
    fontSize: 12,
    fontWeight: 600,
    lineHeight: 1.2,
    padding: `${LABEL_PADDING_Y}px ${LABEL_PADDING_X}px`,
    borderRadius: 4,
    borderWidth: LABEL_BORDER,
    borderStyle: 'solid',
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

function transformFor(c: Candidate, isHorizontal: boolean): string {
    if (c.centerAnchor) {
        return 'translate(-50%, -50%)'
    }
    if (isHorizontal) {
        return c.above ? 'translateY(-50%)' : 'translate(-100%, -50%)'
    }
    return c.above ? 'translate(-50%, -100%)' : 'translateX(-50%)'
}

export function ValueLabels({
    valueFormatter,
    minGap = 4,
    mode = 'per-segment',
}: ValueLabelsProps): React.ReactElement | null {
    const { series, scales, labels, theme, resolvePositionValue, axis } = useChartLayout()
    const isHorizontal = axis.orientation === 'horizontal'
    const isPercent = axis.isPercent

    const formatter = valueFormatter ?? defaultLocaleFormatter

    const visible = useMemo(
        () =>
            applyCollisionAvoidance(
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
                minGap,
                isHorizontal
            ),
        [series, labels, scales, resolvePositionValue, formatter, minGap, isHorizontal, mode, isPercent]
    )

    if (visible.length === 0) {
        return null
    }

    const borderColor = theme.backgroundColor ?? 'white'

    return (
        <>
            {visible.map((c) => (
                <div
                    key={c.key}
                    data-attr="hog-chart-value-label"
                    style={{
                        ...LABEL_STYLE_BASE,
                        backgroundColor: c.color,
                        borderColor,
                        left: Math.round(c.x),
                        top: Math.round(c.y),
                        transform: transformFor(c, isHorizontal),
                    }}
                >
                    {c.text}
                </div>
            ))}
        </>
    )
}
