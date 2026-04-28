import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'

interface AxisLabelsProps {
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    /** Formatter for the right y-axis. Falls back to `yTickFormatter` if not provided. */
    yRightTickFormatter?: (value: number) => string
    hideXAxis?: boolean
    hideYAxis?: boolean
    axisColor?: string
}

const LABEL_FONT = '11px -apple-system, BlinkMacSystemFont, "Inter", "Segoe UI", "Roboto", Helvetica, Arial, sans-serif'
const LABEL_PADDING = 20

let measureCtx: CanvasRenderingContext2D | null = null
function getMeasureCtx(): CanvasRenderingContext2D | null {
    if (!measureCtx) {
        measureCtx = document.createElement('canvas').getContext('2d')
    }
    return measureCtx
}

export function computeVisibleXLabels(
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

    const ctx = getMeasureCtx()
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

const TICK_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    fontSize: 11,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

export function AxisLabels({
    xTickFormatter,
    yTickFormatter,
    yRightTickFormatter,
    hideXAxis,
    hideYAxis,
    axisColor = 'rgba(0, 0, 0, 0.5)',
}: AxisLabelsProps): React.ReactElement | null {
    const { scales, dimensions, labels } = useChartLayout()
    const yTicks = scales.yTicks()

    const rightAxis = useMemo(() => {
        if (!scales.yAxes) {
            return null
        }
        return Object.values(scales.yAxes).find((a) => a.position === 'right') ?? null
    }, [scales.yAxes])
    const rightTicks = useMemo(() => rightAxis?.ticks() ?? [], [rightAxis])

    const visibleXLabels = useMemo(
        () => (hideXAxis ? [] : computeVisibleXLabels(labels, scales.x, xTickFormatter)),
        [hideXAxis, labels, scales.x, xTickFormatter]
    )

    const rightFormatter = yRightTickFormatter ?? yTickFormatter

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
                                ...TICK_STYLE_BASE,
                                right: dimensions.width - dimensions.plotLeft + 8,
                                top: y,
                                transform: 'translateY(-50%)',
                                color: axisColor,
                            }}
                        >
                            {label}
                        </div>
                    )
                })}

            {!hideYAxis &&
                rightAxis &&
                rightTicks.map((tick: number) => {
                    const y = rightAxis.scale(tick)
                    if (!isFinite(y)) {
                        return null
                    }
                    const label = rightFormatter ? rightFormatter(tick) : String(tick)
                    return (
                        <div
                            key={`yr-${tick}`}
                            style={{
                                ...TICK_STYLE_BASE,
                                left: dimensions.plotLeft + dimensions.plotWidth + 8,
                                top: y,
                                transform: 'translateY(-50%)',
                                color: axisColor,
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
                        ...TICK_STYLE_BASE,
                        left: x,
                        top: dimensions.plotTop + dimensions.plotHeight + 8,
                        transform: 'translateX(-50%)',
                        color: axisColor,
                    }}
                >
                    {text}
                </div>
            ))}
        </>
    )
}
