import React from 'react'

import { useChartLayout } from '../core/chart-context'
import { Y_AXIS_TITLE_MARGIN } from '../core/hooks/useChartMargins'
import { TICK_GAP } from '../core/y-axis-gutters'
import { normalizeAxisLabel } from '../utils/axis-labels'
import { AXIS_LABEL_FONT, truncateToWidth } from '../utils/text-measure'

export interface AxisTitlesProps {
    xAxisLabel?: string
    /** Category-axis title for horizontal charts only; vertical titles come per-gutter. */
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
const TITLE_EDGE_PADDING = 8

const truncateAxisTitle = (label: string, maxWidth: number): string => truncateToWidth(label, maxWidth, AXIS_TITLE_FONT)

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

    // Horizontal charts have a category y-axis with no gutter — render its single title at the left
    // edge. Vertical charts title each value gutter on its own side.
    const yTitles: YTitle[] = []
    if (orientation === 'horizontal') {
        const fullYAxisLabel = normalizeAxisLabel(yAxisLabel)
        if (!hideYAxis && fullYAxisLabel) {
            yTitles.push({
                key: 'y-cat',
                x: Y_AXIS_TITLE_X,
                rotation: -90,
                dataAttr: 'hog-chart-axis-title-y',
                label: fullYAxisLabel,
            })
        }
    } else {
        for (const { key, side, offset, width, title } of yGutters) {
            if (!title) {
                continue
            }
            // Sit in the title band just outside this gutter's tick labels (which end at
            // `TICK_GAP + offset + width` from the plot edge), centered in the band.
            const outward = TICK_GAP + offset + width + Y_AXIS_TITLE_MARGIN / 2
            const x =
                side === 'left' ? dimensions.plotLeft - outward : dimensions.plotLeft + dimensions.plotWidth + outward
            yTitles.push({
                key,
                x,
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
