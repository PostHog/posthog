/* eslint-disable react/forbid-dom-props -- dynamic pixel positions from d3 scales */
import React, { useMemo } from 'react'

import type { Series } from '../core/types'
import { useChartLayout } from '../core/chart-context'
import { resolveYScaleForSeries } from '../core/scales'

interface TrendLineOverlayProps {
    /** Pre-computed trend line series (from buildTrendLineSeries). One per source series. */
    trendSeries: Series[]
}

/**
 * Renders trend lines as SVG polylines over any chart type that uses ChartLayoutContext.
 * Designed for bar charts where the underlying BarChart canvas can't draw mixed line/bar —
 * this overlay draws the regression line on top as a DOM element using chart scales.
 * Only supports vertical charts — horizontal bar charts swap axes in a way the SVG layout
 * does not account for, so the overlay returns null for that orientation.
 */
let _nextId = 0

export function TrendLineOverlay({ trendSeries }: TrendLineOverlayProps): React.ReactElement | null {
    // Stable per-instance ID — module counter is deterministic and avoids Math.random().
    // useRef so the ID is allocated once on mount and never changes across re-renders.
    const clipId = React.useRef(`tlo-${_nextId++}`).current
    const { scales, dimensions, labels, axis } = useChartLayout()
    const { plotLeft, plotTop, plotWidth, plotHeight, width, height } = dimensions

    const lines = useMemo(() => {
        // Horizontal bar charts swap the value/band axes — SVG coordinates would be wrong.
        if (axis.orientation === 'horizontal') {
            return []
        }
        return trendSeries
            .filter((s) => !s.visibility?.excluded)
            .map((s) => {
                const yScale = resolveYScaleForSeries(scales, s)
                const points: string[] = []
                for (let i = 0; i < labels.length; i++) {
                    const rawY = s.data[i]
                    if (rawY == null || !isFinite(rawY)) {
                        continue
                    }
                    const x = scales.x(labels[i])
                    const y = yScale(rawY as number)
                    if (!isFinite(x) || !isFinite(y)) {
                        continue
                    }
                    points.push(`${x},${y}`)
                }
                if (points.length < 2) {
                    return null
                }
                const dashArray = s.stroke?.pattern ? s.stroke.pattern.join(',') : '6,4'
                return { key: s.key, points: points.join(' '), color: s.color ?? 'currentColor', dashArray }
            })
            .filter((l): l is NonNullable<typeof l> => l !== null)
    }, [trendSeries, scales, labels, axis.orientation])

    if (lines.length === 0) {
        return null
    }

    return (
        <svg
            style={{
                position: 'absolute',
                left: 0,
                top: 0,
                width,
                height,
                pointerEvents: 'none',
                overflow: 'visible',
            }}
        >
            <clipPath id={clipId}>
                <rect x={plotLeft} y={plotTop} width={plotWidth} height={plotHeight} />
            </clipPath>
            <g clipPath={`url(#${clipId})`}>
                {lines.map(({ key, points, color, dashArray }) => (
                    <polyline
                        key={key}
                        points={points}
                        fill="none"
                        stroke={color}
                        strokeWidth={2}
                        strokeDasharray={dashArray}
                        strokeLinecap="round"
                    />
                ))}
            </g>
        </svg>
    )
}
