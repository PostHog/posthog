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
 *  runs from point to point. Composes as a chart child like {@link ReferenceLine}; renders
 *  null when an endpoint doesn't resolve to a positioned label. */
export function HighlightedRange({
    start,
    end,
    color = DEFAULT_HIGHLIGHT_COLOR,
    fillOpacity = 0.1,
    borderOpacity = 0.8,
}: HighlightedRangeProps): React.ReactElement | null {
    const { labels, scales, dimensions } = useChartLayout()

    const startLabel = typeof start === 'number' ? labels[start] : start
    const endLabel = typeof end === 'number' ? labels[end] : end
    if (startLabel == null || endLabel == null) {
        return null
    }

    const startX = scales.x(startLabel)
    const endX = scales.x(endLabel)
    if (startX == null || endX == null || !isFinite(startX) || !isFinite(endX)) {
        return null
    }

    // Expand each endpoint by half its band so the box covers whole bars; extent is
    // unset on point-style (line) charts, where the box runs from point to point.
    const startHalfBand = (scales.extent?.(startLabel) ?? 0) / 2
    const endHalfBand = (scales.extent?.(endLabel) ?? 0) / 2
    const lo = Math.min(startX - startHalfBand, endX - endHalfBand)
    const hi = Math.max(startX + startHalfBand, endX + endHalfBand)

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const left = Math.max(lo, plotLeft)
    const right = Math.min(hi, plotRight)
    if (right <= left) {
        return null
    }

    const rect: React.CSSProperties = { left, top: plotTop, width: right - left, height: plotHeight }
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
