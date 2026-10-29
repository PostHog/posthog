/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from d3 scales */
import React from 'react'

import { useChartLayout } from '../core/chart-context'

const DEFAULT_BAND_COLOR = '#8f8f8f'

export interface ValueBandProps {
    /** Low end of the band on the value axis. Omit to run the band to the bottom of the plot. */
    from?: number
    /** High end of the band on the value axis. Omit to run the band to the top of the plot. */
    to?: number
    /** CSS color for the fill. Supports `var(--my-color)`. */
    color?: string
    /** Opacity 0-1 of the fill. Defaults to 0.1. */
    fillOpacity?: number
    /** Which y-axis the values reference. Defaults to the primary axis. */
    yAxisId?: string
}

/** Translucent band across the plot between two values on the value axis, e.g. a threshold zone
 *  ("warning between 80 and 95"). The part outside the axis range is clipped, and a band wholly
 *  outside it renders nothing. Draws over the series, like a {@link ReferenceLine} fill, so keep
 *  `fillOpacity` low. On a horizontal bar chart the band runs top to bottom across the value axis. */
export function ValueBand({
    from,
    to,
    color = DEFAULT_BAND_COLOR,
    fillOpacity = 0.1,
    yAxisId,
}: ValueBandProps): React.ReactElement | null {
    const { scales, dimensions, axis } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const scale = yAxisId && scales.yAxes?.[yAxisId] ? scales.yAxes[yAxisId].scale : scales.y
    const horizontal = axis.orientation === 'horizontal'
    const [lo, hi] = horizontal ? [plotLeft, plotLeft + plotWidth] : [plotTop, plotTop + plotHeight]

    // Pixel order flips between orientations, so sort the two ends and clamp both to the plot.
    const ends = [from, to].map((v, i) => {
        if (v != null) {
            return scale(v)
        }
        // A vertical value axis grows upward, a horizontal one rightward.
        return (i === 0) === horizontal ? lo : hi
    })
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
            style={{ ...rect, backgroundColor: color, opacity: fillOpacity }}
        />
    )
}
