import React, { useMemo } from 'react'

import { useChartLayout } from '../../core/chart-context'
import type { PieLayout, PieSlice } from '../../core/radial-layout'
import { useRadialLayout } from '../../core/radial-context'
import type { ChartDimensions } from '../../core/types'
import type { LegendItemClickModifiers } from '../../components/Legend/Legend'
import { FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
import { formatPercent, formatSliceValue } from './SliceLabels'
import type { SliceValueDisplay } from './SliceLabels'

const LABEL_FONT_SIZE = 12
const LABEL_FONT = `${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
const LABEL_HEIGHT = 16
const LABEL_GAP = 2
const LABEL_STEP = LABEL_HEIGHT + LABEL_GAP
// Gap between the name and the value on one label line.
const VALUE_GAP = 6
// The leader starts just off the rim, so it stays visible under a hovered slice's pop-out.
const RIM_GAP = 2
// Radial run before the bend. Longer than the hover pop-out (8px), so the bend clears a grown slice.
const ELBOW_LENGTH = 14
// Horizontal run from the bend to the label column.
const RUN_LENGTH = 10
const TEXT_GAP = 4
// A label column narrower than this cannot show a readable name, so the side stays unlabeled.
const MIN_LABEL_WIDTH = 24

/** Pixels between the pie's rim and the start of the label column. */
export const SURROUNDING_LEADER_SPACE = ELBOW_LENGTH + RUN_LENGTH + TEXT_GAP
/** The label columns never take more than this share of the plot width each, so the pie keeps room. */
export const SURROUNDING_MAX_LABEL_SHARE = 0.3
/** Widest a label column grows, however long the names are. Longer names truncate. */
export const SURROUNDING_MAX_LABEL_WIDTH = 220

export interface SurroundingLabelText {
    name: string
    value?: string
}

export interface SurroundingLabelTextOptions {
    valueFormatter: (value: number) => string
    showValue: boolean
    valueDisplay: SliceValueDisplay
}

/** The text a slice's surrounding label shows: its series label, then its value line if shown. */
export function surroundingLabelText(slice: PieSlice<unknown>, opts: SurroundingLabelTextOptions): SurroundingLabelText {
    return {
        name: slice.series.label,
        value: opts.showValue
            ? formatSliceValue(opts.valueDisplay, opts.valueFormatter(slice.value), formatPercent(slice.fraction))
            : undefined,
    }
}

export function measureSurroundingLabel(text: SurroundingLabelText): number {
    const nameWidth = measureLabelWidth(text.name, LABEL_FONT)
    return text.value ? nameWidth + VALUE_GAP + measureLabelWidth(text.value, LABEL_FONT) : nameWidth
}

/** Pixels to keep free on each side of the pie for the widest label, within the column caps. */
export function surroundingLabelInset(labelWidths: number[], plotWidth: number): number {
    const widest = Math.max(0, ...labelWidths)
    return SURROUNDING_LEADER_SPACE + Math.min(widest, SURROUNDING_MAX_LABEL_WIDTH, plotWidth * SURROUNDING_MAX_LABEL_SHARE)
}

// A slice centered on 12 or 6 o'clock, such as a lone full circle, has a sine that rounds to either
// sign, so ties go right.
const SIDE_EPSILON = 1e-9

function sideOf(angle: number): 'left' | 'right' {
    return Math.sin(angle) > -SIDE_EPSILON ? 'right' : 'left'
}

export interface PlacedSurroundingLabel {
    key: string
    sliceIndex: number
    side: 'left' | 'right'
    /** Vertical center of the label row. */
    y: number
    /** Where the row would sit with no other labels in the way: level with the leader's bend. */
    idealY: number
    /** The label's inner edge: its left edge on the right side, its right edge on the left side. */
    x: number
    maxWidth: number
    /** Leader polyline from the slice's rim to the label: rim point, bend, label end. */
    points: [number, number][]
    color: string
    text: SurroundingLabelText
}

export interface LayoutSurroundingLabelsOptions<Meta> {
    layout: PieLayout<Meta>
    dimensions: Pick<ChartDimensions, 'plotLeft' | 'plotTop' | 'plotWidth' | 'plotHeight'>
    textFor: (slice: PieSlice<Meta>) => SurroundingLabelText
}

/** Places one label per slice in a column on the slice's side of the pie, at the height its
 *  centroid points to. Labels that would overlap are pushed apart along the column and clamped to
 *  the plot. When a side has more slices than rows, its smallest slices go unlabeled. */
export function layoutSurroundingLabels<Meta>({
    layout,
    dimensions,
    textFor,
}: LayoutSurroundingLabelsOptions<Meta>): PlacedSurroundingLabel[] {
    const { cx, cy, outerRadius: r } = layout
    if (r <= 0) {
        return []
    }
    const top = dimensions.plotTop + LABEL_HEIGHT / 2
    const bottom = dimensions.plotTop + dimensions.plotHeight - LABEL_HEIGHT / 2
    const capacity = Math.max(0, Math.floor((dimensions.plotHeight + LABEL_GAP) / LABEL_STEP))
    const columnOffset = r + SURROUNDING_LEADER_SPACE
    const bendRadius = r + ELBOW_LENGTH

    const placed: PlacedSurroundingLabel[] = []
    for (const side of ['left', 'right'] as const) {
        const x = side === 'right' ? cx + columnOffset : cx - columnOffset
        const maxWidth =
            side === 'right' ? dimensions.plotLeft + dimensions.plotWidth - x : x - dimensions.plotLeft
        if (maxWidth < MIN_LABEL_WIDTH) {
            continue
        }

        let candidates = layout.slices
            .map((slice, sliceIndex) => ({ slice, sliceIndex }))
            .filter(({ slice }) => slice.value > 0 && sideOf(slice.centroidAngle) === side)
        if (candidates.length > capacity) {
            const kept = new Set(
                [...candidates]
                    .sort((a, b) => b.slice.value - a.slice.value)
                    .slice(0, capacity)
                    .map((c) => c.sliceIndex)
            )
            candidates = candidates.filter((c) => kept.has(c.sliceIndex))
        }

        const rows = candidates
            .map(({ slice, sliceIndex }) => ({
                slice,
                sliceIndex,
                ideal: cy - Math.cos(slice.centroidAngle) * bendRadius,
            }))
            .sort((a, b) => a.ideal - b.ideal)

        // Push down past the row above, then pull up off the bottom edge, then settle against the
        // top edge again. With rows <= capacity the three passes leave every row inside the plot.
        const ys = rows.map((row) => row.ideal)
        for (let i = 0; i < ys.length; i++) {
            ys[i] = Math.max(ys[i], top, i > 0 ? ys[i - 1] + LABEL_STEP : -Infinity)
        }
        for (let i = ys.length - 1; i >= 0; i--) {
            ys[i] = Math.min(ys[i], bottom, i < ys.length - 1 ? ys[i + 1] - LABEL_STEP : Infinity)
        }
        for (let i = 0; i < ys.length; i++) {
            ys[i] = Math.max(ys[i], top, i > 0 ? ys[i - 1] + LABEL_STEP : -Infinity)
        }

        const direction = side === 'right' ? 1 : -1
        rows.forEach(({ slice, sliceIndex }, i) => {
            const sin = Math.sin(slice.centroidAngle)
            const cos = Math.cos(slice.centroidAngle)
            placed.push({
                key: slice.series.key || String(sliceIndex),
                sliceIndex,
                side,
                y: ys[i],
                idealY: rows[i].ideal,
                x,
                maxWidth,
                points: [
                    [cx + sin * (r + RIM_GAP), cy - cos * (r + RIM_GAP)],
                    [cx + sin * bendRadius, cy - cos * bendRadius],
                    [cx + direction * (r + ELBOW_LENGTH + RUN_LENGTH), ys[i]],
                ],
                color: slice.color,
                text: textFor(slice),
            })
        })
    }
    return placed
}

const START_ANGLE_STEPS = 24

/** Picks where the first slice starts so the labels move least from their slices. A run of thin
 *  slices at 12 o'clock stacks its labels down a whole column, with leader lines crossing the pie;
 *  turned to face a side, the same run fans straight out to the labels. Tries every 15°, keeps 12
 *  o'clock unless another angle is clearly better, and counts a slice left unlabeled as a label
 *  moved the full plot height. */
export function pickSurroundingStartAngle<Meta>(
    layoutAt: (startAngle: number) => PieLayout<Meta>,
    dimensions: LayoutSurroundingLabelsOptions<Meta>['dimensions']
): number {
    let best = 0
    let bestCost = Infinity
    for (let step = 0; step < START_ANGLE_STEPS; step++) {
        const startAngle = (step * 2 * Math.PI) / START_ANGLE_STEPS
        const layout = layoutAt(startAngle)
        const placed = layoutSurroundingLabels({ layout, dimensions, textFor: () => ({ name: '' }) })
        const unlabeled = layout.slices.filter((slice) => slice.value > 0).length - placed.length
        const cost =
            placed.reduce((sum, label) => sum + Math.abs(label.y - label.idealY), 0) +
            unlabeled * dimensions.plotHeight
        if (cost < bestCost - 1) {
            best = startAngle
            bestCost = cost
        }
    }
    return best
}

export interface SurroundingLabelsProps extends SurroundingLabelTextOptions {
    /** Called when a label is clicked, as a legend row click. Omit for static labels. */
    onLabelClick?: (key: string, modifiers: LegendItemClickModifiers) => void
}

const SVG_STYLE: React.CSSProperties = {
    position: 'absolute',
    left: 0,
    top: 0,
    overflow: 'visible',
    pointerEvents: 'none',
}

const LABEL_STYLE: React.CSSProperties = {
    position: 'absolute',
    display: 'flex',
    gap: VALUE_GAP,
    alignItems: 'baseline',
    fontSize: LABEL_FONT_SIZE,
    lineHeight: `${LABEL_HEIGHT}px`,
    whiteSpace: 'nowrap',
    transform: 'translateY(-50%)',
    // Reset for the clickable variant, which renders as a button.
    background: 'none',
    border: 0,
    padding: 0,
    margin: 0,
    font: 'inherit',
    color: 'inherit',
}

const NAME_STYLE: React.CSSProperties = { overflow: 'hidden', textOverflow: 'ellipsis', minWidth: 0 }

/** The `'surrounding'` legend: each slice's name (and value line, if shown) in a column beside the
 *  pie, joined to its slice by a leader line in the slice's color. Reads the radial layout, so it
 *  renders as a child of `<PieChart>`. */
export function SurroundingLabels({
    valueFormatter,
    showValue,
    valueDisplay,
    onLabelClick,
}: SurroundingLabelsProps): React.ReactElement | null {
    const { layout } = useRadialLayout()
    const { dimensions, theme } = useChartLayout()

    const placed = useMemo(
        () =>
            layoutSurroundingLabels({
                layout,
                dimensions,
                textFor: (slice) => surroundingLabelText(slice, { valueFormatter, showValue, valueDisplay }),
            }),
        [layout, dimensions, valueFormatter, showValue, valueDisplay]
    )

    if (placed.length === 0) {
        return null
    }

    return (
        <>
            <svg
                width={dimensions.width}
                height={dimensions.height}
                style={SVG_STYLE}
                data-attr="hog-chart-pie-leader-lines"
                aria-hidden
            >
                {placed.map((label) => (
                    <polyline
                        key={label.key}
                        points={label.points.map(([px, py]) => `${px},${py}`).join(' ')}
                        fill="none"
                        stroke={label.color}
                        strokeWidth={1}
                    />
                ))}
            </svg>
            {placed.map((label) => {
                const title = label.text.value ? `${label.text.name}: ${label.text.value}` : label.text.name
                const style: React.CSSProperties = {
                    ...LABEL_STYLE,
                    top: Math.round(label.y),
                    maxWidth: Math.floor(label.maxWidth),
                    ...(label.side === 'right'
                        ? { left: Math.round(label.x) }
                        : { right: Math.round(dimensions.width - label.x), justifyContent: 'flex-end' }),
                    cursor: onLabelClick ? 'pointer' : undefined,
                    pointerEvents: onLabelClick ? 'auto' : 'none',
                }
                const content = (
                    <>
                        <span style={NAME_STYLE}>{label.text.name}</span>
                        {label.text.value ? (
                            <span style={{ flexShrink: 0, color: theme.axisColor }}>{label.text.value}</span>
                        ) : null}
                    </>
                )
                return onLabelClick ? (
                    <button
                        key={label.key}
                        type="button"
                        title={title}
                        style={style}
                        data-attr="hog-chart-pie-surrounding-label"
                        data-side={label.side}
                        data-hog-charts-interactive-overlay=""
                        onClick={(e) =>
                            onLabelClick(label.key, { additive: e.metaKey || e.ctrlKey || e.shiftKey })
                        }
                    >
                        {content}
                    </button>
                ) : (
                    <div
                        key={label.key}
                        title={title}
                        style={style}
                        data-attr="hog-chart-pie-surrounding-label"
                        data-side={label.side}
                    >
                        {content}
                    </div>
                )
            })}
        </>
    )
}
