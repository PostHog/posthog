import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import { AXIS_LABEL_FONT, getTextMeasureCtx, truncateToWidth } from '../utils/text-measure'

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
    /** When set, truncate category tick labels wider than this (px) with an ellipsis and reveal
     *  the full value on hover. Omitted (default) renders labels untruncated. */
    maxCategoryLabelWidth?: number
}

const LABEL_PADDING = 20

export function computeVisibleXLabels(
    labels: string[],
    xScale: (label: string) => number | undefined,
    formatter?: (value: string, index: number) => string | null,
    maxCategoryLabelWidth = 0
): { index: number; text: string; fullText: string; x: number }[] {
    const candidates: { index: number; text: string; fullText: string; x: number }[] = []
    for (let i = 0; i < labels.length; i++) {
        const x = xScale(labels[i])
        if (x == null) {
            continue
        }
        const fullText = formatter ? formatter(labels[i], i) : labels[i]
        if (fullText === null) {
            continue
        }
        // When a max width is set, truncate for display and overlap measurement; the full value
        // is revealed on hover. A non-positive width leaves the label untruncated.
        const text = truncateToWidth(fullText, maxCategoryLabelWidth)
        candidates.push({ index: i, text, fullText, x })
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

    const visible: { index: number; text: string; fullText: string; x: number }[] = []
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

const TICK_GAP = 8

interface ChartBox {
    width: number
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

// When a label is truncated, `title` carries the full value so it can be revealed on hover.
// Hovering needs pointer events, which the base style disables, so re-enable them just for titled labels.
const titleStyle = (title?: string): React.CSSProperties => (title ? { pointerEvents: 'auto' } : {})

function YTickLabel({
    y,
    side,
    box,
    text,
    color,
    dataAttr,
    title,
}: {
    y: number
    side: 'left' | 'right'
    box: ChartBox
    text: string
    color: string
    dataAttr: string
    title?: string
}): React.ReactElement {
    const edge =
        side === 'left'
            ? { right: box.width - box.plotLeft + TICK_GAP }
            : { left: box.plotLeft + box.plotWidth + TICK_GAP }
    return (
        <div
            data-attr={dataAttr}
            title={title}
            style={{ ...TICK_STYLE_BASE, ...titleStyle(title), ...edge, top: y, transform: 'translateY(-50%)', color }}
        >
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
    title,
}: {
    x: number
    box: ChartBox
    text: string
    color: string
    dataAttr: string
    title?: string
}): React.ReactElement {
    return (
        <div
            data-attr={dataAttr}
            title={title}
            style={{
                ...TICK_STYLE_BASE,
                ...titleStyle(title),
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
    maxCategoryLabelWidth = 0,
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
            hideXAxis || orientation === 'horizontal'
                ? []
                : computeVisibleXLabels(labels, scales.x, xTickFormatter, maxCategoryLabelWidth),
        [hideXAxis, labels, scales.x, xTickFormatter, orientation, maxCategoryLabelWidth]
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
                        const fullText = xTickFormatter ? xTickFormatter(labelText, i) : labelText
                        if (fullText === null) {
                            return null
                        }
                        const y = labelToY(labelText)
                        if (y == null || !isFinite(y)) {
                            return null
                        }
                        const text = truncateToWidth(fullText, maxCategoryLabelWidth)
                        return (
                            <YTickLabel
                                key={`y-cat-${i}`}
                                y={y}
                                side="left"
                                box={dimensions}
                                text={text}
                                title={text !== fullText ? fullText : undefined}
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

            {visibleXLabels.map(({ index, text, fullText, x }) => (
                <XTickLabel
                    key={`x-${index}`}
                    x={x}
                    box={dimensions}
                    text={text}
                    title={text !== fullText ? fullText : undefined}
                    color={axisColor}
                    dataAttr="hog-chart-axis-tick-x"
                />
            ))}
        </>
    )
}
