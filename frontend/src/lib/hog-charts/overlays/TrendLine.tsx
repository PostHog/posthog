import * as d3 from 'd3'
import React from 'react'

import { linearRegression } from '../core/interaction'
import type { ChartDimensions, Series } from '../core/types'

interface TrendLineProps {
    series: Series[]
    labels: string[]
    xScale: d3.ScalePoint<string>
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    dimensions: ChartDimensions
    incompleteFromIndex?: number
}

export function TrendLine({
    series,
    labels,
    xScale,
    yScale,
    dimensions,
    incompleteFromIndex,
}: TrendLineProps): React.ReactElement {
    return (
        <>
            {series.map((s) => {
                if (s.hidden) {
                    return null
                }

                const endIdx = incompleteFromIndex ?? s.data.length
                const regression = linearRegression(s.data, endIdx)
                if (!regression) {
                    return null
                }

                const startX = xScale(labels[0])
                const endX = xScale(labels[Math.min(endIdx - 1, labels.length - 1)])
                if (startX == null || endX == null) {
                    return null
                }

                const startY = yScale(regression.intercept)
                const endY = yScale(regression.slope * (endIdx - 1) + regression.intercept)

                if (!isFinite(startY) || !isFinite(endY)) {
                    return null
                }

                // Use SVG for the dotted trend line overlay
                return (
                    <svg
                        key={`trend-${s.key}`}
                        style={{
                            position: 'absolute',
                            left: 0,
                            top: 0,
                            width: dimensions.width,
                            height: dimensions.height,
                            pointerEvents: 'none',
                        }}
                    >
                        <line
                            x1={startX}
                            y1={startY}
                            x2={endX}
                            y2={endY}
                            stroke={s.color}
                            strokeWidth={1.5}
                            strokeDasharray="4 4"
                            opacity={0.6}
                        />
                    </svg>
                )
            })}
        </>
    )
}
