/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from d3 scales */
import React from 'react'

import { useChartLayout } from 'lib/hog-charts'

import type { AnomalyMarker } from './anomalyPointsAdapter'

interface AnomalyPointsLayerProps {
    markers: AnomalyMarker[]
    /** Radius of each marker in CSS pixels. Defaults to 3, matching the legacy chart.js style. */
    radius?: number
}

/** Renders alert anomaly points as small filled circles positioned by the chart's scales.
 *
 *  Sits on top of the canvas so the dots stay crisp when the chart re-renders. We render
 *  via DOM rather than canvas so the points don't compete with the line/area drawing
 *  pipeline (a sibling Series<>` would force `drawLine` to stitch a connecting line through
 *  NaN values — `tracePath` doesn't reset on gaps, see `core/canvas-renderer.ts`). */
export function AnomalyPointsLayer({ markers, radius = 3 }: AnomalyPointsLayerProps): React.ReactElement | null {
    const { scales, dimensions, labels } = useChartLayout()
    if (!markers.length) {
        return null
    }

    const { plotLeft, plotTop, plotWidth, plotHeight } = dimensions
    const plotRight = plotLeft + plotWidth
    const plotBottom = plotTop + plotHeight

    const dots: React.ReactElement[] = []
    for (const marker of markers) {
        const label = labels[marker.dataIndex]
        const x = label != null ? scales.x(label) : undefined
        if (x == null || !isFinite(x)) {
            continue
        }
        const yScaleFn = scales.yAxes?.[marker.yAxisId]?.scale ?? scales.y
        const y = yScaleFn(marker.value)
        if (!isFinite(y) || x < plotLeft || x > plotRight || y < plotTop || y > plotBottom) {
            continue
        }
        const diameter = radius * 2
        dots.push(
            <div
                key={`${marker.dataIndex}-${marker.yAxisId}`}
                className="absolute pointer-events-none rounded-full"
                style={{
                    left: x - radius,
                    top: y - radius,
                    width: diameter,
                    height: diameter,
                    backgroundColor: marker.color,
                }}
            />
        )
    }

    return <>{dots}</>
}
