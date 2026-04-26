import React, { useMemo } from 'react'

import { useChart } from '../core/chart-context'
import { DEFAULT_Y_AXIS_ID } from '../core/types'
import type { ChartScales, Series } from '../core/types'

export interface ValueLabelsProps {
    /** Formats the value shown on each label. Defaults to `value.toLocaleString()`. */
    valueFormatter?: (value: number, seriesIndex: number, dataIndex: number) => string
    /** Minimum horizontal gap (in px) required between adjacent labels. Defaults to 4. */
    minGap?: number
    /** Series with more than this many data points are skipped entirely to avoid
     *  rendering hundreds of DOM nodes on dense charts. Defaults to 100. */
    maxPointsPerSeries?: number
}

const LABEL_FONT =
    '600 12px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'
const LABEL_VERTICAL_OFFSET = 0

let measureCtx: CanvasRenderingContext2D | null = null
function getMeasureCtx(): CanvasRenderingContext2D | null {
    if (!measureCtx) {
        measureCtx = document.createElement('canvas').getContext('2d')
    }
    return measureCtx
}

const LABEL_HEIGHT = 22

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

function resolveYScale(s: Series, scales: ChartScales): (value: number) => number {
    const axisId = s.yAxisId ?? DEFAULT_Y_AXIS_ID
    return scales.yAxes?.[axisId]?.scale ?? scales.y
}

function buildCandidates(
    series: Series[],
    labels: string[],
    scales: ChartScales,
    valueFormatter: ValueLabelsProps['valueFormatter'],
    maxPointsPerSeries: number
): Candidate[] {
    const ctx = getMeasureCtx()
    if (ctx) {
        ctx.font = LABEL_FONT
    }

    const candidates: Candidate[] = []

    for (let sIdx = 0; sIdx < series.length; sIdx++) {
        const s = series[sIdx]
        if (s.hidden || s.hideValueLabels) {
            continue
        }
        if (s.data.length > maxPointsPerSeries) {
            continue
        }
        const yScale = resolveYScale(s, scales)

        for (let dIdx = 0; dIdx < s.data.length && dIdx < labels.length; dIdx++) {
            const value = s.data[dIdx]
            if (typeof value !== 'number' || value === 0 || !isFinite(value)) {
                continue
            }
            const x = scales.x(labels[dIdx])
            if (x == null || !isFinite(x)) {
                continue
            }
            const y = yScale(value)
            if (!isFinite(y)) {
                continue
            }
            const text = valueFormatter ? valueFormatter(value, sIdx, dIdx) : value.toLocaleString()
            const width = ctx ? ctx.measureText(text).width : text.length * 6
            candidates.push({
                key: `${s.key}-${dIdx}`,
                seriesIndex: sIdx,
                text,
                x,
                y,
                width,
                color: s.color,
                above: value >= 0,
            })
        }
    }

    return candidates
}

function labelRect(c: Candidate): { left: number; right: number; top: number; bottom: number } {
    const halfW = c.width / 2
    const top = c.above ? c.y - LABEL_HEIGHT : c.y
    return { left: c.x - halfW, right: c.x + halfW, top, bottom: top + LABEL_HEIGHT }
}

function rectsOverlap(
    a: { left: number; right: number; top: number; bottom: number },
    b: { left: number; right: number; top: number; bottom: number },
    gap: number
): boolean {
    return a.left < b.right + gap && a.right + gap > b.left && a.top < b.bottom + gap && a.bottom + gap > b.top
}

function applyCollisionAvoidance(candidates: Candidate[], minGap: number): Candidate[] {
    if (candidates.length === 0) {
        return candidates
    }

    // First pass: per-series horizontal dedup
    const bySeries: Map<number, Candidate[]> = new Map()
    for (const c of candidates) {
        const bucket = bySeries.get(c.seriesIndex)
        if (bucket) {
            bucket.push(c)
        } else {
            bySeries.set(c.seriesIndex, [c])
        }
    }

    const afterHorizontal: Candidate[] = []
    for (const group of bySeries.values()) {
        group.sort((a, b) => a.x - b.x)
        let lastRightEdge = -Infinity
        for (const c of group) {
            const halfWidth = c.width / 2
            const leftEdge = c.x - halfWidth
            if (leftEdge >= lastRightEdge + minGap) {
                afterHorizontal.push(c)
                lastRightEdge = c.x + halfWidth
            }
        }
    }

    // Second pass: cross-series 2D overlap removal (earlier series win)
    const visible: Candidate[] = []
    const placedRects: { left: number; right: number; top: number; bottom: number }[] = []
    for (const c of afterHorizontal) {
        const rect = labelRect(c)
        const overlaps = placedRects.some((placed) => rectsOverlap(rect, placed, minGap))
        if (!overlaps) {
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
    border: '2px solid white',
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

export function ValueLabels({
    valueFormatter,
    minGap = 4,
    maxPointsPerSeries = 100,
}: ValueLabelsProps): React.ReactElement | null {
    const { series, scales, labels } = useChart()

    const visible = useMemo(() => {
        const candidates = buildCandidates(series, labels, scales, valueFormatter, maxPointsPerSeries)
        return applyCollisionAvoidance(candidates, minGap)
    }, [series, labels, scales, valueFormatter, minGap, maxPointsPerSeries])

    if (visible.length === 0) {
        return null
    }

    return (
        <>
            {visible.map((c) => {
                const style: React.CSSProperties = {
                    ...LABEL_STYLE_BASE,
                    backgroundColor: c.color,
                    left: Math.round(c.x),
                    top: Math.round(c.above ? c.y : c.y + LABEL_VERTICAL_OFFSET),
                    transform: c.above
                        ? `translate(-50%, calc(-100% - ${LABEL_VERTICAL_OFFSET}px))`
                        : 'translateX(-50%)',
                }
                return (
                    <div key={c.key} data-attr="hog-chart-value-label" style={style}>
                        {c.text}
                    </div>
                )
            })}
        </>
    )
}
