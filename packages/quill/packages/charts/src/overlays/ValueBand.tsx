/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from d3 scales */
import React from 'react'

import { useChartLayout } from '../core/chart-context'
import { DEFAULT_HIGHLIGHT_COLOR } from './HighlightedRange'

export interface ValueBandProps {
    /** Low end of the band on the value axis. Omit to run the band to the bottom of the plot. */
    from?: number
    /** High end of the band on the value axis. Omit to run the band to the top of the plot. */
    to?: number
    /** CSS color for the fill. Supports `var(--my-color)`. Defaults to the theme's axis color. */
    color?: string
    /** Opacity 0-1 of the fill. Defaults to 0.1. */
    fillOpacity?: number
    /** Defaults to the primary axis. */
    yAxisId?: string
}

/** Translucent band between two values on the value axis. Draws over the series, so keep `fillOpacity` low. */
export function ValueBand({ from, to, color, fillOpacity = 0.1, yAxisId }: ValueBandProps): React.ReactElement | null {
    const { scales, dimensions, axis, theme } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const scale = yAxisId && scales.yAxes?.[yAxisId] ? scales.yAxes[yAxisId].scale : scales.y
    const horizontal = axis.orientation === 'horizontal'
    const [lo, hi] = horizontal ? [plotLeft, plotLeft + plotWidth] : [plotTop, plotTop + plotHeight]
    const [axisMinEdge, axisMaxEdge] = horizontal ? [lo, hi] : [hi, lo]

    const ends = [from == null ? axisMinEdge : scale(from), to == null ? axisMaxEdge : scale(to)]
    if (!ends.every(isFinite)) {
        return null
    }
    const start = Math.max(lo, Math.min(...ends))
    const end = Math.min(hi, Math.max(...ends))
    if (end <= start) {
        return null
    }

    const rect: React.CSSProperties = horizontal
        ? { left: start, width: end - start, top: plotTop, height: plotHeight }
        : { left: plotLeft, width: plotWidth, top: start, height: end - start }
    return (
        <div
            data-attr="hog-chart-value-band"
            className="absolute pointer-events-none"
            style={{
                ...rect,
                backgroundColor: color ?? theme.axisColor ?? DEFAULT_HIGHLIGHT_COLOR,
                opacity: fillOpacity,
            }}
        />
    )
}
