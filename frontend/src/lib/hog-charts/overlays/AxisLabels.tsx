import React, { useMemo } from 'react'

import { useChart } from '../core/chart-context'

interface AxisLabelsProps {
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    hideXAxis?: boolean
    hideYAxis?: boolean
    axisColor?: string
}

const LABEL_FONT = '11px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'
const LABEL_PADDING = 20

function computeVisibleXLabels(
    labels: string[],
    xScale: (label: string) => number | undefined,
    formatter?: (value: string, index: number) => string | null
): { index: number; text: string; x: number }[] {
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

    const canvas = document.createElement('canvas')
    const ctx = canvas.getContext('2d')
    if (!ctx) {
        return candidates
    }
    ctx.font = LABEL_FONT

    const widths = candidates.map((c) => ctx.measureText(c.text).width)

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
    xTickFormatter,
    yTickFormatter,
    hideXAxis,
    hideYAxis,
    axisColor = 'rgba(0, 0, 0, 0.5)',
}: AxisLabelsProps): React.ReactElement | null {
    const { scales, dimensions, labels } = useChart()
    const yTicks = scales.yRaw.ticks?.() ?? []

    const visibleXLabels = useMemo(
        () => (hideXAxis ? [] : computeVisibleXLabels(labels, scales.x, xTickFormatter)),
        [hideXAxis, labels, scales.x, xTickFormatter]
    )

    return (
        <>
            {!hideYAxis &&
                yTicks.map((tick: number) => {
                    const y = scales.y(tick)
                    if (!isFinite(y)) {
                        return null
                    }
                    const label = yTickFormatter ? yTickFormatter(tick) : String(tick)
                    return (
                        <div
                            key={`y-${tick}`}
                            style={{
                                position: 'absolute',
                                right: dimensions.width - dimensions.plotLeft + 8,
                                top: y,
                                transform: 'translateY(-50%)',
                                fontSize: 11,
                                color: axisColor,
                                pointerEvents: 'none',
                                whiteSpace: 'nowrap',
                            }}
                        >
                            {label}
                        </div>
                    )
                })}

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
