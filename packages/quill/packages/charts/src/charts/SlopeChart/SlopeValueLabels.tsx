import React, { useMemo } from 'react'

import { useChartLayout } from '../../core/chart-context'
import type { ResolvedSeries } from '../../core/types'
import { defaultValueFormatter, slopeEnd, slopeLabelVisible, type SlopeSide, slopeStart } from './slope-data'
import { SlopeLabel } from './SlopeLabel'

export interface SlopeValueLabelsProps {
    valueFormatter?: (value: number) => string
    /** Chart-level default for the start (left) value labels. Per-series `meta.showStartLabel` wins. */
    showStartLabels?: boolean
    /** Chart-level default for the end (right) value labels. Per-series `meta.showEndLabel` wins. */
    showEndLabels?: boolean
    /** Px gap between the point and its value label. */
    gap?: number
    /** Min vertical px between two labels in the same column before the lower one is dropped. */
    minGap?: number
}

interface ValueCandidate {
    key: string
    side: SlopeSide
    text: string
    color: string
    x: number
    y: number
}

const LABEL_HEIGHT = 16

/** Keep labels in one column top-to-bottom, dropping any that would crowd the one above it. */
function columnSweep(candidates: ValueCandidate[], minGap: number): ValueCandidate[] {
    const sorted = [...candidates].sort((a, b) => a.y - b.y)
    const kept: ValueCandidate[] = []
    const halfH = LABEL_HEIGHT / 2
    let lastBottom = -Infinity
    for (const c of sorted) {
        if (c.y - halfH >= lastBottom + minGap) {
            kept.push(c)
            lastBottom = c.y + halfH
        }
    }
    return kept
}

/** Start (left) and end (right) value labels for a slope chart, one per series per side. Each side
 *  is a vertical column anchored on the points; within a column, lower-priority labels are
 *  dropped on collision. Per-series visibility comes from `meta.showStartLabel`/`showEndLabel`. */
export function SlopeValueLabels({
    valueFormatter = defaultValueFormatter,
    showStartLabels = true,
    showEndLabels = true,
    gap = 8,
    minGap = 2,
}: SlopeValueLabelsProps): React.ReactElement | null {
    const { series, scales, labels } = useChartLayout()

    const visible = useMemo(() => {
        if (labels.length < 2) {
            return []
        }
        const x0 = scales.x(labels[0])
        const x1 = scales.x(labels[labels.length - 1])
        const start: ValueCandidate[] = []
        const end: ValueCandidate[] = []
        for (const s of series as ResolvedSeries[]) {
            if (slopeLabelVisible(s, 'start', showStartLabels) && x0 != null) {
                const y = scales.y(slopeStart(s))
                if (isFinite(y)) {
                    start.push({
                        key: s.key,
                        side: 'start',
                        text: valueFormatter(slopeStart(s)),
                        color: s.color,
                        x: x0,
                        y,
                    })
                }
            }
            if (slopeLabelVisible(s, 'end', showEndLabels) && x1 != null) {
                const y = scales.y(slopeEnd(s))
                if (isFinite(y)) {
                    end.push({ key: s.key, side: 'end', text: valueFormatter(slopeEnd(s)), color: s.color, x: x1, y })
                }
            }
        }
        return [...columnSweep(start, minGap), ...columnSweep(end, minGap)]
    }, [series, scales, labels, valueFormatter, showStartLabels, showEndLabels, minGap])

    if (visible.length === 0) {
        return null
    }

    return (
        <>
            {visible.map((c) => (
                <SlopeLabel
                    key={`${c.side}-${c.key}`}
                    x={c.x}
                    y={c.y}
                    transform={
                        c.side === 'start' ? `translate(calc(-100% - ${gap}px), -50%)` : `translate(${gap}px, -50%)`
                    }
                    color={c.color}
                    text={c.text}
                    dataAttr="hog-chart-slope-value-label"
                    side={c.side}
                />
            ))}
        </>
    )
}
