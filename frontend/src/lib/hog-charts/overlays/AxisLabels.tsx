import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import { getTextMeasureCtx, LABEL_FONT } from '../utils/text-measure'

interface AxisLabelsProps {
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    /** Formatter for the right y-axis. Falls back to `yTickFormatter` if not provided. */
    yRightTickFormatter?: (value: number) => string
    hideXAxis?: boolean
    hideYAxis?: boolean
    axisColor?: string
    orientation?: 'vertical' | 'horizontal'
    /** Optional override for label → coord mapping. Falls back to `scales.x`, which chart types
     *  serving horizontal orientation are expected to set to a label→band-center function. */
    labelToCoord?: (label: string) => number | undefined
}

const LABEL_PADDING = 20

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

    const ctx = getTextMeasureCtx()
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
    fontSize: 12,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

/** Distance in CSS pixels between the plot edge and the start of the tick label. */
const TICK_GAP = 8

interface ChartBox {
    width: number
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

/** Tick label sitting alongside a y-axis. `side` picks which axis: `left` anchors to the
 *  right of the plot's left edge; `right` anchors to the left of the plot's right edge. */
function YTickLabel({
    y,
    side,
    box,
    text,
    color,
    dataAttr,
}: {
    y: number
    side: 'left' | 'right'
    box: ChartBox
    text: string
    color: string
    dataAttr: string
}): React.ReactElement {
    const edge =
        side === 'left'
            ? { right: box.width - box.plotLeft + TICK_GAP }
            : { left: box.plotLeft + box.plotWidth + TICK_GAP }
    return (
        <div data-attr={dataAttr} style={{ ...TICK_STYLE_BASE, ...edge, top: y, transform: 'translateY(-50%)', color }}>
            {text}
        </div>
    )
}

/** Tick label sitting under the x-axis (the chart's bottom edge). */
function XTickLabel({
    x,
    box,
    text,
    color,
    dataAttr,
}: {
    x: number
    box: ChartBox
    text: string
    color: string
    dataAttr: string
}): React.ReactElement {
    return (
        <div
            data-attr={dataAttr}
            style={{
                ...TICK_STYLE_BASE,
                left: x,
                top: box.plotTop + box.plotHeight + TICK_GAP,
                transform: 'translateX(-50%)',
                color,
            }}
        >
            {text}
        </div>
    )
}

export function AxisLabels({
    xTickFormatter,
    yTickFormatter,
    yRightTickFormatter,
    hideXAxis,
    hideYAxis,
    axisColor = 'rgba(0, 0, 0, 0.5)',
    orientation = 'vertical',
    labelToCoord,
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
        () =>
            hideXAxis || orientation === 'horizontal' ? [] : computeVisibleXLabels(labels, scales.x, xTickFormatter),
        [hideXAxis, labels, scales.x, xTickFormatter, orientation]
    )

    const rightFormatter = yRightTickFormatter ?? yTickFormatter

    if (orientation === 'horizontal') {
        // In horizontal mode `scales.y` holds value→x-pixel and the label→y-pixel function lives
        // on `scales.x` (or `labelToCoord` if explicitly overridden).
        const labelToY = labelToCoord ?? scales.x
        return (
            <>
                {!hideYAxis &&
                    labels.map((labelText, i) => {
                        const text = xTickFormatter ? xTickFormatter(labelText, i) : labelText
                        if (text === null) {
                            return null
                        }
                        const y = labelToY(labelText)
                        if (y == null || !isFinite(y)) {
                            return null
                        }
                        return (
                            <YTickLabel
                                key={`y-cat-${i}`}
                                y={y}
                                side="left"
                                box={dimensions}
                                text={text}
                                color={axisColor}
                                dataAttr="hog-chart-axis-tick-y"
                            />
                        )
                    })}
                {!hideXAxis &&
                    yTicks.map((tick: number) => {
                        const x = scales.y(tick)
                        if (!isFinite(x)) {
                            return null
                        }
                        const label = yTickFormatter ? yTickFormatter(tick) : String(tick)
                        return (
                            <XTickLabel
                                key={`x-val-${tick}`}
                                x={x}
                                box={dimensions}
                                text={label}
                                color={axisColor}
                                dataAttr="hog-chart-axis-tick-x"
                            />
                        )
                    })}
            </>
        )
    }

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
                        <YTickLabel
                            key={`y-${tick}`}
                            y={y}
                            side="left"
                            box={dimensions}
                            text={label}
                            color={axisColor}
                            dataAttr="hog-chart-axis-tick-y"
                        />
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
                        <YTickLabel
                            key={`yr-${tick}`}
                            y={y}
                            side="right"
                            box={dimensions}
                            text={label}
                            color={axisColor}
                            dataAttr="hog-chart-axis-tick-yr"
                        />
                    )
                })}

            {visibleXLabels.map(({ index, text, x }) => (
                <XTickLabel
                    key={`x-${index}`}
                    x={x}
                    box={dimensions}
                    text={text}
                    color={axisColor}
                    dataAttr="hog-chart-axis-tick-x"
                />
            ))}
        </>
    )
}
