import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import { AXIS_LABEL_FONT, getTextMeasureCtx } from '../utils/text-measure'

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
    ctx.font = AXIS_LABEL_FONT

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

// Category tick labels are a fixed ~12px tall (see TICK_STYLE_BASE.fontSize); require this much
// center-to-center spacing so stacked rows stay legible. The vertical x-axis uses LABEL_PADDING
// for the same purpose on width — this is its band-axis analogue for horizontal charts.
const Y_LABEL_LINE_HEIGHT = 12
const Y_LABEL_PADDING = 4

/** Horizontal-orientation analogue of `computeVisibleXLabels`: returns the subset of category
 *  (band) labels that fit down the y-axis without overlapping. When the plot is tall enough every
 *  label clears the previous one and all are kept; when bands are compressed (e.g. a small
 *  dashboard tile with many breakdowns) it thins them out evenly instead of stacking them into an
 *  unreadable band. Label height is constant, so no per-label text measurement is needed. */
export function computeVisibleYLabels(
    labels: string[],
    yScale: (label: string) => number | undefined,
    formatter?: (value: string, index: number) => string | null
): { index: number; text: string; y: number }[] {
    const candidates: { index: number; text: string; y: number }[] = []
    for (let i = 0; i < labels.length; i++) {
        const text = formatter ? formatter(labels[i], i) : labels[i]
        if (text === null) {
            continue
        }
        const y = yScale(labels[i])
        if (y == null || !isFinite(y)) {
            continue
        }
        candidates.push({ index: i, text, y })
    }

    // Greedy from the top: keep a label only when it clears the last kept label's bottom edge plus
    // padding, so the rendered set never overlaps regardless of how many bands are packed in.
    candidates.sort((a, b) => a.y - b.y)
    const visible: { index: number; text: string; y: number }[] = []
    let lastBottomEdge = -Infinity
    const halfHeight = Y_LABEL_LINE_HEIGHT / 2
    for (const candidate of candidates) {
        if (candidate.y - halfHeight >= lastBottomEdge + Y_LABEL_PADDING) {
            visible.push(candidate)
            lastBottomEdge = candidate.y + halfHeight
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

const TICK_GAP = 8

interface ChartBox {
    width: number
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

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

    // In horizontal mode `scales.y` holds value→x-pixel and the label→y-pixel function lives on
    // `scales.x` (or `labelToCoord` if explicitly overridden). Thin out overlapping category labels.
    const visibleYLabels = useMemo(
        () =>
            hideYAxis || orientation !== 'horizontal'
                ? []
                : computeVisibleYLabels(labels, labelToCoord ?? scales.x, xTickFormatter),
        [hideYAxis, orientation, labels, labelToCoord, scales.x, xTickFormatter]
    )

    const rightFormatter = yRightTickFormatter ?? yTickFormatter

    if (orientation === 'horizontal') {
        return (
            <>
                {visibleYLabels.map(({ index, text, y }) => (
                    <YTickLabel
                        key={`y-cat-${index}`}
                        y={y}
                        side="left"
                        box={dimensions}
                        text={text}
                        color={axisColor}
                        dataAttr="hog-chart-axis-tick-y"
                    />
                ))}
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
