import * as d3 from 'd3'
import React from 'react'

import type { ChartDimensions, Series } from '../core/types'

interface DataLabelsProps {
    series: Series[]
    labels: string[]
    xScale: d3.ScalePoint<string>
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    dimensions: ChartDimensions
    formatter?: (value: number, seriesIndex: number) => string
    stackedData?: Map<string, number[]>
}

interface LabelPosition {
    x: number
    y: number
    text: string
}

export function DataLabels({
    series,
    labels,
    xScale,
    yScale,
    dimensions,
    formatter,
    stackedData,
}: DataLabelsProps): React.ReactElement {
    const allLabels: LabelPosition[] = []

    series.forEach((s, si) => {
        if (s.hidden) {
            return
        }
        const data = stackedData?.get(s.key) ?? s.data
        for (let i = 0; i < data.length; i++) {
            const x = xScale(labels[i])
            const y = yScale(data[i])
            if (x == null || !isFinite(y)) {
                continue
            }
            const text = formatter ? formatter(data[i], si) : String(Math.round(data[i] * 100) / 100)
            allLabels.push({ x, y: y - 12, text })
        }
    })

    // Simple collision detection: skip labels that overlap
    const rendered: LabelPosition[] = []
    const MIN_GAP = 30

    for (const label of allLabels) {
        const overlaps = rendered.some((r) => Math.abs(r.x - label.x) < MIN_GAP && Math.abs(r.y - label.y) < 14)
        if (!overlaps) {
            rendered.push(label)
        }
    }

    return (
        <>
            {rendered.map((label, i) => {
                if (label.x < dimensions.plotLeft || label.x > dimensions.plotLeft + dimensions.plotWidth) {
                    return null
                }
                return (
                    <div
                        key={i}
                        style={{
                            position: 'absolute',
                            left: label.x,
                            top: label.y,
                            transform: 'translateX(-50%)',
                            fontSize: 10,
                            fontWeight: 500,
                            color: 'rgba(0, 0, 0, 0.7)',
                            pointerEvents: 'none',
                            whiteSpace: 'nowrap',
                        }}
                    >
                        {label.text}
                    </div>
                )
            })}
        </>
    )
}
