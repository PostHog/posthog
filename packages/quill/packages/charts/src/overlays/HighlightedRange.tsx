/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from d3 scales */
import React from 'react'

import { useChartLayout } from '../core/chart-context'

/** Neutral gray matching the classic sparkline highlight, readable on light and dark surfaces. */
const DEFAULT_HIGHLIGHT_COLOR = '#8f8f8f'

export interface HighlightedRangeProps {
    /** Start of the range — a data index (number) or an x-axis label (string). */
    start: number | string
    /** End of the range, inclusive — a data index (number) or an x-axis label (string). */
    end: number | string
    /** CSS color for the fill and border. Supports `var(--my-color)`. */
    color?: string
    /** Opacity 0-1 of the translucent fill. Defaults to 0.1. */
    fillOpacity?: number
    /** Opacity 0-1 of the 1px border marking the range edges. Defaults to 0.8. Pass 0 for no border. */
    borderOpacity?: number
}

/** Translucent box spanning an x-axis label/index range — mirrors an external selection
 *  (e.g. the rows currently visible in a paired virtualized list) onto the chart. On band
 *  (bar) charts the box covers the full bands of both endpoints; on point (line) charts it
 *  runs from point to point, and a single point gets half the gap to its neighbors on each
 *  side so it stays visible. On horizontal charts it spans the selected rows. Composes as a
 *  chart child like {@link ReferenceLine}; renders null when an endpoint doesn't resolve to a
 *  positioned label. It draws no label, so name the range with a vertical
 *  {@link ReferenceLine} whose `value` is the start label. */
export function HighlightedRange({
    start,
    end,
    color = DEFAULT_HIGHLIGHT_COLOR,
    fillOpacity = 0.1,
    borderOpacity = 0.8,
}: HighlightedRangeProps): React.ReactElement | null {
    const { labels, scales, dimensions, axis } = useChartLayout()

    const startIndex = typeof start === 'number' ? start : labels.indexOf(start)
    const endIndex = typeof end === 'number' ? end : labels.indexOf(end)
    const startLabel = labels[startIndex]
    const endLabel = labels[endIndex]
    if (startLabel == null || endLabel == null) {
        return null
    }

    const startPos = scales.x(startLabel)
    const endPos = scales.x(endLabel)
    if (startPos == null || endPos == null || !isFinite(startPos) || !isFinite(endPos)) {
        return null
    }

    // Positions run along the categorical axis, which is y on a horizontal chart.
    const horizontal = axis.orientation === 'horizontal'
    // Half of each endpoint's band, so the box covers whole bars. Point-style charts have no
    // extent: their box runs point to point, except a single point or a horizontal chart's rows,
    // which take half the gap to the neighboring label instead.
    const halfGap = (index: number): number => {
        const here = scales.x(labels[index]) ?? 0
        const neighbor = scales.x(labels[index + 1] ?? labels[index - 1] ?? '')
        return neighbor != null && isFinite(neighbor) ? Math.abs(neighbor - here) / 2 : 0
    }
    const pointSpan = horizontal || startPos === endPos
    const halfBand = (label: string, index: number): number => {
        const extent = scales.extent?.(label)
        if (extent != null) {
            return extent / 2
        }
        return pointSpan ? halfGap(index) : 0
    }
    const startHalf = halfBand(startLabel, startIndex)
    const endHalf = halfBand(endLabel, endIndex)
    const lo = Math.min(startPos - startHalf, endPos - endHalf)
    const hi = Math.max(startPos + startHalf, endPos + endHalf)

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const axisStart = horizontal ? plotTop : plotLeft
    const axisEnd = horizontal ? plotTop + plotHeight : plotLeft + plotWidth
    const from = Math.max(lo, axisStart)
    const to = Math.min(hi, axisEnd)
    if (to <= from) {
        return null
    }

    const rect: React.CSSProperties = horizontal
        ? { left: plotLeft, top: from, width: plotWidth, height: to - from }
        : { left: from, top: plotTop, width: to - from, height: plotHeight }
    return (
        <>
            <div
                data-attr="hog-chart-highlighted-range"
                className="absolute pointer-events-none"
                style={{ ...rect, backgroundColor: color, opacity: fillOpacity }}
            />
            {borderOpacity > 0 && (
                <div
                    className="absolute pointer-events-none"
                    style={{
                        ...rect,
                        borderWidth: 1,
                        borderStyle: 'solid',
                        borderColor: color,
                        opacity: borderOpacity,
                    }}
                />
            )}
        </>
    )
}
