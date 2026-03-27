import * as d3 from 'd3'
import React, { useMemo } from 'react'

import type { ChartDimensions } from '../core/types'

interface AxisLabelsProps {
    dimensions: ChartDimensions
    xScale: d3.ScalePoint<string>
    yScale: d3.ScaleLinear<number, number> | d3.ScaleLogarithmic<number, number>
    labels: string[]
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    hideXAxis?: boolean
    hideYAxis?: boolean
    axisColor?: string
    /** Side for this Y axis ('left' or 'right') */
    yAxisSide?: 'left' | 'right'
}

const LABEL_FONT = '11px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'
const LABEL_PADDING = 20 // minimum px gap between labels, matches Chart.js autoSkipPadding

/** Greedy auto-skip: walk left-to-right keeping a label only when it won't overlap the previous one. */
function computeVisibleXLabels(
    labels: string[],
    xScale: d3.ScalePoint<string>,
    formatter?: (value: string, index: number) => string | null
): { index: number; text: string; x: number }[] {
    // Build candidate list with formatted text and pixel position
    const candidates: { index: number; text: string; x: number }[] = []
    for (let i = 0; i < labels.length; i++) {
        const x = xScale(labels[i])
        if (x == null) {
            continue
        }
        const text = formatter ? formatter(labels[i], i) : labels[i]
        if (text === null) {
            continue
        }
        candidates.push({ index: i, text, x })
    }

    if (candidates.length === 0) {
        return []
    }

    // Measure text widths using an offscreen canvas
    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        return candidates
    }
    ctx.font = LABEL_FONT

    const widths = candidates.map((c) => ctx.measureText(c.text).width)

    // Greedy: always show first label, then skip any that would overlap
    const visible: { index: number; text: string; x: number }[] = []
    let lastRightEdge = -Infinity

    for (let i = 0; i < candidates.length; i++) {
        const halfWidth = widths[i] / 2
        const leftEdge = candidates[i].x - halfWidth

        if (leftEdge >= lastRightEdge + LABEL_PADDING) {
            visible.push(candidates[i])
            lastRightEdge = candidates[i].x + halfWidth
        }
    }

    return visible
}

export function AxisLabels({
    dimensions,
    xScale,
    yScale,
    labels,
    xTickFormatter,
    yTickFormatter,
    hideXAxis,
    hideYAxis,
    axisColor = 'rgba(0, 0, 0, 0.5)',
    yAxisSide = 'left',
}: AxisLabelsProps): React.ReactElement | null {
    const yTicks = (yScale as d3.ScaleLinear<number, number>).ticks?.() ?? []

    const visibleXLabels = useMemo(
        () => (hideXAxis ? [] : computeVisibleXLabels(labels, xScale, xTickFormatter)),
        [hideXAxis, labels, xScale, xTickFormatter]
    )

    return (
        <>
            {/* Y-axis labels */}
            {!hideYAxis &&
                yTicks.map((tick) => {
                    const y = yScale(tick)
                    if (!isFinite(y)) {
                        return null
                    }
                    const label = yTickFormatter ? yTickFormatter(tick) : String(tick)
                    const style: React.CSSProperties =
                        yAxisSide === 'right'
                            ? {
                                  position: 'absolute',
                                  left: dimensions.plotLeft + dimensions.plotWidth + 8,
                                  top: y,
                                  transform: 'translateY(-50%)',
                                  fontSize: 11,
                                  color: axisColor,
                                  pointerEvents: 'none',
                                  whiteSpace: 'nowrap',
                              }
                            : {
                                  position: 'absolute',
                                  right: dimensions.width - dimensions.plotLeft + 8,
                                  top: y,
                                  transform: 'translateY(-50%)',
                                  fontSize: 11,
                                  color: axisColor,
                                  pointerEvents: 'none',
                                  whiteSpace: 'nowrap',
                              }
                    return (
                        <div key={`y-${tick}`} style={style}>
                            {label}
                        </div>
                    )
                })}

            {/* X-axis labels */}
            {visibleXLabels.map(({ index, text, x }) => (
                <div
                    key={`x-${index}`}
                    style={{
                        position: 'absolute',
                        left: x,
                        top: dimensions.plotTop + dimensions.plotHeight + 8,
                        transform: 'translateX(-50%)',
                        fontSize: 11,
                        color: axisColor,
                        pointerEvents: 'none',
                        whiteSpace: 'nowrap',
                    }}
                >
                    {text}
                </div>
            ))}
        </>
    )
}
