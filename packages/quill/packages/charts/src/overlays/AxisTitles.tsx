import React from 'react'

import { useChartLayout } from '../core/chart-context'
import { Y_AXIS_TITLE_MARGIN } from '../core/hooks/useChartMargins'
import { normalizeAxisLabel } from '../utils/axis-labels'
import { AXIS_LABEL_FONT, measureLabelWidth } from '../utils/text-measure'

export interface AxisTitlesProps {
    xAxisLabel?: string
    /** Category-axis (left) title for horizontal charts, which have no value gutter to hang a title
     *  on. Ignored for vertical charts, whose titles come per-gutter from the shared layout. */
    yAxisLabel?: string
    hideXAxis?: boolean
    hideYAxis?: boolean
    orientation?: 'vertical' | 'horizontal'
    axisColor: string
}

const AXIS_TITLE_STYLE: React.CSSProperties = {
    fontSize: 12,
    fontWeight: 500,
    pointerEvents: 'none',
}
const AXIS_TITLE_FONT = `500 ${AXIS_LABEL_FONT}`

const SVG_STYLE: React.CSSProperties = {
    position: 'absolute',
    top: 0,
    left: 0,
    width: '100%',
    height: '100%',
    pointerEvents: 'none',
    overflow: 'visible',
}

const X_AXIS_TITLE_BASELINE_OFFSET = 6
const Y_AXIS_TITLE_X = 12
// Matches AxisLabels' tick gutter gap — the title clears the tick labels by the same amount.
const TICK_GAP = 8
const TITLE_EDGE_PADDING = 8
const ELLIPSIS = '…'

function measureAxisTitleWidth(label: string): number {
    const measured = measureLabelWidth(label, AXIS_TITLE_FONT)
    const fallback = label.length * 7
    return measured > 0 ? measured : fallback
}

function truncateAxisTitle(label: string, maxWidth: number): string {
    if (maxWidth <= 0 || measureAxisTitleWidth(label) <= maxWidth) {
        return label
    }

    const ellipsisWidth = measureAxisTitleWidth(ELLIPSIS)
    if (ellipsisWidth >= maxWidth) {
        return ELLIPSIS
    }

    let low = 0
    let high = label.length
    while (low < high) {
        const mid = Math.ceil((low + high) / 2)
        const candidate = `${label.slice(0, mid).trimEnd()}${ELLIPSIS}`
        if (measureAxisTitleWidth(candidate) <= maxWidth) {
            low = mid
        } else {
            high = mid - 1
        }
    }

    return `${label.slice(0, low).trimEnd()}${ELLIPSIS}`
}

interface YTitle {
    key: string
    x: number
    rotation: -90 | 90
    dataAttr: string
    label: string
}

export function AxisTitles({
    xAxisLabel,
    yAxisLabel,
    hideXAxis,
    hideYAxis,
    orientation = 'vertical',
    axisColor,
}: AxisTitlesProps): React.ReactElement | null {
    const { dimensions, yGutters } = useChartLayout()
    const fullXAxisLabel = normalizeAxisLabel(xAxisLabel)
    const showXAxisTitle = !hideXAxis && !!fullXAxisLabel

    // Horizontal charts have a category (not value) y-axis with no gutter — render its single title
    // at the left edge, the way the old single-axis path did. Vertical charts title each value
    // gutter on its own side, from the shared layout.
    const yTitles: YTitle[] = []
    if (orientation === 'horizontal') {
        const fullYAxisLabel = normalizeAxisLabel(yAxisLabel)
        if (!hideYAxis && fullYAxisLabel) {
            yTitles.push({ key: 'y-cat', x: Y_AXIS_TITLE_X, rotation: -90, dataAttr: 'hog-chart-axis-title-y', label: fullYAxisLabel })
        }
    } else {
        for (const { key, side, offset, width, title } of yGutters) {
            if (!title) {
                continue
            }
            // Sit in the title band just outside this gutter's tick labels (which end at
            // `TICK_GAP + offset + width` from the plot edge), centered in the band.
            const outward = TICK_GAP + offset + width + Y_AXIS_TITLE_MARGIN / 2
            yTitles.push({
                key,
                x: side === 'left' ? dimensions.plotLeft - outward : dimensions.plotLeft + dimensions.plotWidth + outward,
                rotation: side === 'left' ? -90 : 90,
                dataAttr: side === 'left' ? 'hog-chart-axis-title-y' : 'hog-chart-axis-title-yr',
                label: title,
            })
        }
    }

    if (!showXAxisTitle && yTitles.length === 0) {
        return null
    }

    const xCenter = dimensions.plotLeft + dimensions.plotWidth / 2
    const xBaseline = dimensions.height - X_AXIS_TITLE_BASELINE_OFFSET
    const yCenter = dimensions.plotTop + dimensions.plotHeight / 2
    const maxYTitleWidth = Math.max(0, dimensions.plotHeight - TITLE_EDGE_PADDING * 2)
    const xTitle = fullXAxisLabel
        ? truncateAxisTitle(fullXAxisLabel, Math.max(0, dimensions.plotWidth - TITLE_EDGE_PADDING * 2))
        : undefined

    return (
        <svg aria-hidden="true" style={SVG_STYLE}>
            {showXAxisTitle && xTitle && (
                <text
                    data-attr="hog-chart-axis-title-x"
                    data-full-label={fullXAxisLabel}
                    x={xCenter}
                    y={xBaseline}
                    fill={axisColor}
                    textAnchor="middle"
                    style={AXIS_TITLE_STYLE}
                >
                    {xTitle}
                </text>
            )}
            {yTitles.map(({ key, x, rotation, dataAttr, label }) => (
                <text
                    key={key}
                    data-attr={dataAttr}
                    data-full-label={label}
                    x={x}
                    y={yCenter}
                    fill={axisColor}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    transform={`rotate(${rotation} ${x} ${yCenter})`}
                    style={AXIS_TITLE_STYLE}
                >
                    {truncateAxisTitle(label, maxYTitleWidth)}
                </text>
            ))}
        </svg>
    )
}
