import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import { DEFAULT_Y_AXIS_ID } from '../core/types'
import type { ChartScales, ResolvedSeries, ResolveValueFn } from '../core/types'

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
const STACK_TOTAL_KEY = '__stack_total__'

let measureCtx: CanvasRenderingContext2D | null = null
function getMeasureCtx(): CanvasRenderingContext2D | null {
    if (!measureCtx) {
        measureCtx = document.createElement('canvas').getContext('2d')
    }
    return measureCtx
}

interface Candidate {
    key: string
    seriesIndex: number
    text: string
    x: number
    y: number
    width: number
    color: string
    above: boolean
}

function resolveYScale(s: { yAxisId?: string }, scales: ChartScales): (value: number) => number {
    const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
    return scales.yAxes?.[axisId]?.scale ?? scales.y
}

function defaultLocaleFormatter(v: number): string {
    return v.toLocaleString()
}

interface BuildCandidatesArgs {
    series: ResolvedSeries[]
    labels: string[]
    scales: ChartScales
    resolveValue: ResolveValueFn
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
    above: boolean
): void {
    const width = ctx ? ctx.measureText(text).width : text.length * 6
    out.push({
        key,
        seriesIndex,
        text,
        x: isHorizontal ? valueCoord : categoricalCoord,
        y: isHorizontal ? categoricalCoord : valueCoord,
        width,
        color,
        above,
    })
}

function buildCandidates(args: BuildCandidatesArgs): Candidate[] {
    const ctx = getMeasureCtx()
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
    const visible = series.filter((s) => !s.visibility?.excluded && !s.visibility?.fromValueLabels)
    if (visible.length === 0) {
        return out
    }
    const topSeries = visible[visible.length - 1]
    const yScale = resolveYScale(topSeries, scales)
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
    const { series, labels, scales, resolveValue, valueFormatter, isHorizontal } = args
    const out: Candidate[] = []

    for (let sIdx = 0; sIdx < series.length; sIdx++) {
        const s = series[sIdx]
        if (s.visibility?.excluded || s.visibility?.fromValueLabels) {
            continue
        }
        const yScale = resolveYScale(s, scales)
        for (let dIdx = 0; dIdx < s.data.length && dIdx < labels.length; dIdx++) {
            const rawValue = s.data[dIdx]
            if (typeof rawValue !== 'number' || !isFinite(rawValue) || rawValue === 0) {
                continue
            }
            const yValue = resolveValue(s, dIdx)
            if (typeof yValue !== 'number' || !isFinite(yValue)) {
                continue
            }
            const categoricalCoord = scales.x(labels[dIdx])
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
                valueFormatter(rawValue, sIdx, dIdx),
                categoricalCoord,
                valueCoord,
                yValue >= 0
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
        const left = c.above ? c.x : c.x - c.width
        return { left, right: left + c.width, top: c.y - halfH, bottom: c.y + halfH }
    }
    const halfW = c.width / 2
    const top = c.above ? c.y - LABEL_HEIGHT : c.y
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
    padding: '2px 4px',
    borderRadius: 4,
    borderWidth: 2,
    borderStyle: 'solid',
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

function transformFor(c: Candidate, isHorizontal: boolean): string {
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
    const { series, scales, labels, theme, resolveValue, axisOrientation, isPercent } = useChartLayout()
    const isHorizontal = axisOrientation === 'horizontal'

    const formatter = valueFormatter ?? defaultLocaleFormatter

    const visible = useMemo(
        () =>
            applyCollisionAvoidance(
                buildCandidates({
                    series,
                    labels,
                    scales,
                    resolveValue,
                    valueFormatter: formatter,
                    isHorizontal,
                    mode,
                    isPercent,
                }),
                minGap,
                isHorizontal
            ),
        [series, labels, scales, resolveValue, formatter, minGap, isHorizontal, mode, isPercent]
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
