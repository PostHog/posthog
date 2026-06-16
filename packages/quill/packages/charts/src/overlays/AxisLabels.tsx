import React, { useMemo } from 'react'

import { useChartLayout } from '../core/chart-context'
import { GUTTER_GAP } from '../core/hooks/useChartMargins'
import { autoFormatterFor } from '../core/scales'
import { AXIS_LABEL_FONT, getTextMeasureCtx, measureLabelWidth, truncateToWidth } from '../utils/text-measure'

interface AxisLabelsProps {
    xTickFormatter?: (value: string, index: number) => string | null
    yTickFormatter?: (value: number) => string
    /** The *unresolved* user y-tick formatter (config). When set, every stacked axis uses it; when
     *  unset, each axis auto-formats against its own ticks. Only consulted for the multi-axis path. */
    userYTickFormatter?: (value: number) => string
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

// Minimum gap (px) required between adjacent kept labels. Category labels are often words and get
// generous breathing room; uniformly-spaced numeric value ticks read clearly much closer, so forcing
// the category gap on them culls ticks that have plenty of room.
const CATEGORY_LABEL_PADDING = 20
const VALUE_TICK_LABEL_PADDING = 8

interface XLabelCandidate {
    index: number
    /** Display text — truncated to `maxCategoryLabelWidth` when one is set. */
    text: string
    /** Full value, present only when `text` was truncated, so hover can reveal it. */
    title?: string
    x: number
}

/** Truncate a category label for display; carry the full value as `title` only when it was cut. */
function truncateWithTitle(fullText: string, maxCategoryLabelWidth: number): { text: string; title?: string } {
    const text = truncateToWidth(fullText, maxCategoryLabelWidth)
    return { text, title: text === fullText ? undefined : fullText }
}

/** Greedily keep entries left→right, dropping any whose centered label would collide with the
 *  previously kept one (closer than `padding` px). Entries must be sorted by ascending `x`. */
function dropOverlappingLabels<T extends { text: string; x: number }>(candidates: T[], padding: number): T[] {
    if (candidates.length === 0) {
        return []
    }

    const ctx = getTextMeasureCtx()
    if (!ctx) {
        return candidates
    }
    ctx.font = AXIS_LABEL_FONT

    const visible: T[] = []
    let lastRightEdge = -Infinity

    for (const candidate of candidates) {
        const halfWidth = ctx.measureText(candidate.text).width / 2
        const leftEdge = candidate.x - halfWidth

        if (leftEdge >= lastRightEdge + padding) {
            visible.push(candidate)
            lastRightEdge = candidate.x + halfWidth
        }
    }

    return visible
}

export function computeVisibleXLabels(
    labels: string[],
    xScale: (label: string) => number | undefined,
    formatter?: (value: string, index: number) => string | null,
    maxCategoryLabelWidth = 0
): XLabelCandidate[] {
    const candidates: XLabelCandidate[] = []
    for (let i = 0; i < labels.length; i++) {
        const x = xScale(labels[i])
        if (x == null) {
            continue
        }
        const fullText = formatter ? formatter(labels[i], i) : labels[i]
        if (fullText === null) {
            continue
        }
        // The truncated text drives both display and overlap measurement below.
        const { text, title } = truncateWithTitle(fullText, maxCategoryLabelWidth)
        candidates.push({ index: i, text, title, x })
    }

    return dropOverlappingLabels(candidates, CATEGORY_LABEL_PADDING)
}

interface ValueTickCandidate {
    tick: number
    text: string
    x: number
}

/** Value-axis ticks for a horizontal bar chart map onto the x-axis, where wide numeric labels
 *  (e.g. "450,000") collide far more readily than stacked y-axis labels do. Greedily drop the
 *  ones that would overlap so the axis stays legible — the same pass `computeVisibleXLabels`
 *  applies to a vertical chart's category axis. Ticks arrive value-sorted, so ascending value
 *  maps to ascending x for an increasing value scale. */
export function computeVisibleValueTicks(
    ticks: number[],
    valueToCoord: (value: number) => number,
    formatter?: (value: number) => string
): ValueTickCandidate[] {
    const candidates: ValueTickCandidate[] = []
    for (const tick of ticks) {
        const x = valueToCoord(tick)
        if (!isFinite(x)) {
            continue
        }
        candidates.push({ tick, text: formatter ? formatter(tick) : String(tick), x })
    }

    return dropOverlappingLabels(candidates, VALUE_TICK_LABEL_PADDING)
}

const TICK_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    fontSize: 12,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

const TICK_GAP = 8

/** One stacked value-axis gutter: its ticks, scale, side, and outward pixel offset from the plot edge. */
interface Gutter {
    key: string
    side: 'left' | 'right'
    offset: number
    ticks: number[]
    scale: (v: number) => number
    formatter: (v: number) => string
}

interface ChartBox {
    width: number
    plotLeft: number
    plotTop: number
    plotWidth: number
    plotHeight: number
}

// When a label is truncated, `title` carries the full value so it can be revealed on hover.
// Hovering needs pointer events, which the base style disables, so re-enable them just for titled labels.
const TITLE_POINTER_STYLE: React.CSSProperties = { pointerEvents: 'auto' }
const NO_POINTER_STYLE: React.CSSProperties = {}
const titleStyle = (title?: string): React.CSSProperties => (title ? TITLE_POINTER_STYLE : NO_POINTER_STYLE)

function YTickLabel({
    y,
    side,
    box,
    text,
    color,
    dataAttr,
    title,
    offset = 0,
}: {
    y: number
    side: 'left' | 'right'
    box: ChartBox
    text: string
    color: string
    dataAttr: string
    title?: string
    /** Extra px pushing this gutter outward (away from the plot) so stacked axes don't overlap. */
    offset?: number
}): React.ReactElement {
    const edge =
        side === 'left'
            ? { right: box.width - box.plotLeft + TICK_GAP + offset }
            : { left: box.plotLeft + box.plotWidth + TICK_GAP + offset }
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

export const AxisLabels = React.memo(function AxisLabels({
    xTickFormatter,
    yTickFormatter,
    userYTickFormatter,
    hideXAxis,
    hideYAxis,
    axisColor = 'rgba(0, 0, 0, 0.5)',
    orientation = 'vertical',
    labelToCoord,
    maxCategoryLabelWidth = 0,
}: AxisLabelsProps): React.ReactElement | null {
    const { scales, dimensions, labels } = useChartLayout()
    const yTicks = scales.yTicks()

    // Vertical value-axis gutters, stacked outward per side. With per-axis scales (`scales.yAxes`,
    // i.e. `showMultipleYAxes`) we render one gutter per axis — each labelled with its own ticks and
    // offset by the cumulative width of the inner gutters. Without, a single left gutter from the
    // shared scale (`scales.y` / `scales.yTicks`). Each axis auto-formats against its own ticks
    // unless the caller supplied an explicit formatter, in which case every axis shares it.
    const yGutters = useMemo(() => {
        if (hideYAxis || orientation === 'horizontal') {
            return []
        }
        if (!scales.yAxes) {
            return [
                {
                    key: 'y-left',
                    side: 'left' as const,
                    offset: 0,
                    ticks: yTicks,
                    scale: scales.y,
                    formatter: yTickFormatter ?? autoFormatterFor(yTicks),
                },
            ] satisfies Gutter[]
        }
        const widthOf = (ticks: number[], formatter: (v: number) => string): number =>
            ticks.reduce((widest, t) => Math.max(widest, measureLabelWidth(formatter(t))), 0)
        let leftCum = 0
        let rightCum = 0
        const gutters: Gutter[] = []
        Object.entries(scales.yAxes).forEach(([axisId, axis]) => {
            const ticks = axis.ticks()
            const formatter = userYTickFormatter ?? autoFormatterFor(ticks)
            const offset = axis.position === 'left' ? leftCum : rightCum
            gutters.push({ key: `y-${axisId}`, side: axis.position, offset, ticks, scale: axis.scale, formatter })
            const width = widthOf(ticks, formatter) + GUTTER_GAP
            if (axis.position === 'left') {
                leftCum += width
            } else {
                rightCum += width
            }
        })
        return gutters
    }, [hideYAxis, orientation, scales.yAxes, scales.y, yTicks, yTickFormatter, userYTickFormatter])

    const visibleXLabels = useMemo(
        () =>
            hideXAxis || orientation === 'horizontal'
                ? []
                : computeVisibleXLabels(labels, scales.x, xTickFormatter, maxCategoryLabelWidth),
        [hideXAxis, labels, scales.x, xTickFormatter, orientation, maxCategoryLabelWidth]
    )

    // Mirror the vertical branch's memoization so an unrelated prop change (e.g. axisColor)
    // doesn't re-run the per-tick `ctx.measureText` measurements in `dropOverlappingLabels`.
    const visibleValueTicks = useMemo(
        () =>
            hideXAxis || orientation !== 'horizontal' ? [] : computeVisibleValueTicks(yTicks, scales.y, yTickFormatter),
        [hideXAxis, orientation, yTicks, scales.y, yTickFormatter]
    )

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
                        const { text, title } = truncateWithTitle(fullText, maxCategoryLabelWidth)
                        return (
                            <YTickLabel
                                key={`y-cat-${i}`}
                                y={y}
                                side="left"
                                box={dimensions}
                                text={text}
                                title={title}
                                color={axisColor}
                                dataAttr="hog-chart-axis-tick-y"
                            />
                        )
                    })}
                {visibleValueTicks.map(({ tick, text, x }) => (
                    <XTickLabel
                        key={`x-val-${tick}`}
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

    return (
        <>
            {yGutters.flatMap((gutter) =>
                gutter.ticks.map((tick: number) => {
                    const y = gutter.scale(tick)
                    if (!isFinite(y)) {
                        return null
                    }
                    return (
                        <YTickLabel
                            key={`${gutter.key}-${tick}`}
                            y={y}
                            side={gutter.side}
                            offset={gutter.offset}
                            box={dimensions}
                            text={gutter.formatter(tick)}
                            color={axisColor}
                            dataAttr={gutter.side === 'left' ? 'hog-chart-axis-tick-y' : 'hog-chart-axis-tick-yr'}
                        />
                    )
                })
            )}

            {visibleXLabels.map(({ index, text, title, x }) => (
                <XTickLabel
                    key={`x-${index}`}
                    x={x}
                    box={dimensions}
                    text={text}
                    title={title}
                    color={axisColor}
                    dataAttr="hog-chart-axis-tick-x"
                />
            ))}
        </>
    )
})
