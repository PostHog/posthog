/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from the layout */
import React, { useMemo } from 'react'

import { useChartLayout } from '../../core/chart-context'
import { FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
import { readHistogramLayout } from './histogram-scales'

const DEFAULT_MARKER_COLOR = 'rgba(0, 0, 0, 0.5)'
const LABEL_FONT_SIZE = 11
const LABEL_FONT = `500 ${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
const LABEL_OFFSET = 3
const LABEL_GAP = 6
/** Top margin a chart with markers reserves, so labels sit above the plot instead of over the bars. */
export const MARKER_LABEL_MARGIN = 24
const LABEL_BOTTOM_GAP = 6

export interface ResolvedHistogramMarker {
    key: string
    label: string
    value: number
    valueText: string
    color?: string
}

interface PlacedLabel {
    text: string
    left: number
}

/** One row of labels above the plot. Each label sits beside its line, on the left when the next
 *  marker is close enough to collide, and falls back to its short form, then to no label. */
export function placeMarkerLabels(
    markers: { x: number; label: string; full: string }[],
    containerWidth: number,
    measure: (text: string) => number
): (PlacedLabel | null)[] {
    let lastRight = -Infinity
    return markers.map((marker, i) => {
        const fullWidth = measure(marker.full)
        const next = markers[i + 1]
        const crowdedOnRight = !!next && next.x - marker.x < fullWidth + LABEL_OFFSET + LABEL_GAP
        const sides: ('left' | 'right')[] = crowdedOnRight ? ['left', 'right'] : ['right', 'left']
        for (const text of marker.full === marker.label ? [marker.full] : [marker.full, marker.label]) {
            const width = text === marker.full ? fullWidth : measure(text)
            for (const side of sides) {
                const left = side === 'right' ? marker.x + LABEL_OFFSET : marker.x - LABEL_OFFSET - width
                if (left >= 0 && left + width <= containerWidth && left >= lastRight + LABEL_GAP) {
                    lastRight = left + width
                    return { text, left }
                }
            }
        }
        return null
    })
}

export function HistogramMarkers({ markers }: { markers: ResolvedHistogramMarker[] }): React.ReactElement | null {
    const { scales, dimensions, theme } = useChartLayout()
    const layout = readHistogramLayout(scales)

    const positioned = useMemo(() => {
        if (!layout) {
            return []
        }
        // Filter on the value, since the log scale clamps and would pin an outside marker to the edge.
        const [lo, hi] = layout.xScale.domain()
        return markers
            .filter((marker) => marker.value >= lo && marker.value <= hi)
            .map((marker) => ({ ...marker, x: Math.round(layout.xScale(marker.value)) }))
            .filter((marker) => isFinite(marker.x))
            .sort((a, b) => a.x - b.x)
    }, [layout, markers])

    const labels = useMemo(
        () =>
            placeMarkerLabels(
                positioned.map((m) => ({ x: m.x, label: m.label, full: `${m.label} ${m.valueText}` })),
                dimensions.width,
                (text) => measureLabelWidth(text, LABEL_FONT)
            ),
        [positioned, dimensions.width]
    )

    if (!positioned.length) {
        return null
    }
    const labelTop = dimensions.plotTop - LABEL_BOTTOM_GAP - LABEL_FONT_SIZE
    return (
        <>
            {positioned.map((marker, i) => {
                const color = marker.color ?? theme.axisColor ?? DEFAULT_MARKER_COLOR
                const label = labels[i]
                return (
                    <React.Fragment key={marker.key}>
                        <div
                            data-attr="hog-chart-histogram-marker"
                            className="absolute pointer-events-none"
                            style={{
                                left: marker.x,
                                top: dimensions.plotTop,
                                height: dimensions.plotHeight,
                                borderLeft: `1px dashed ${color}`,
                            }}
                        />
                        {label && (
                            <div
                                data-attr="hog-chart-histogram-marker-label"
                                className="absolute pointer-events-none whitespace-nowrap font-medium tabular-nums"
                                style={{
                                    left: label.left,
                                    top: labelTop,
                                    fontSize: LABEL_FONT_SIZE,
                                    lineHeight: `${LABEL_FONT_SIZE}px`,
                                    color,
                                }}
                            >
                                {label.text}
                            </div>
                        )}
                    </React.Fragment>
                )
            })}
        </>
    )
}
