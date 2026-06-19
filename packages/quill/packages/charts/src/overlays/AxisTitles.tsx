import React from 'react'

import { useChartLayout } from '../core/chart-context'
import { normalizeAxisLabel } from '../utils/axis-labels'
import { AXIS_LABEL_FONT, measureLabelWidth } from '../utils/text-measure'

export interface AxisTitlesProps {
    xAxisLabel?: string
    yAxisLabel?: string
    hideXAxis?: boolean
    hideYAxis?: boolean
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
const ELLIPSIS = '\u2026'

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

export function AxisTitles({
    xAxisLabel,
    yAxisLabel,
    hideXAxis,
    hideYAxis,
    axisColor,
}: AxisTitlesProps): React.ReactElement | null {
    const { dimensions } = useChartLayout()
    const fullXAxisLabel = normalizeAxisLabel(xAxisLabel)
    const fullYAxisLabel = normalizeAxisLabel(yAxisLabel)
    const showXAxisTitle = !hideXAxis && !!fullXAxisLabel
    const showYAxisTitle = !hideYAxis && !!fullYAxisLabel

    if (!showXAxisTitle && !showYAxisTitle) {
        return null
    }

    const xCenter = dimensions.plotLeft + dimensions.plotWidth / 2
    const xBaseline = dimensions.height - X_AXIS_TITLE_BASELINE_OFFSET
    const yCenter = dimensions.plotTop + dimensions.plotHeight / 2
    const xTitle = fullXAxisLabel
        ? truncateAxisTitle(fullXAxisLabel, Math.max(0, dimensions.plotWidth - TITLE_EDGE_PADDING * 2))
        : undefined
    const yTitle = fullYAxisLabel
        ? truncateAxisTitle(fullYAxisLabel, Math.max(0, dimensions.plotHeight - TITLE_EDGE_PADDING * 2))
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
            {showYAxisTitle && yTitle && (
                <text
                    data-attr="hog-chart-axis-title-y"
                    data-full-label={fullYAxisLabel}
                    x={Y_AXIS_TITLE_X}
                    y={yCenter}
                    fill={axisColor}
                    textAnchor="middle"
                    dominantBaseline="middle"
                    transform={`rotate(-90 ${Y_AXIS_TITLE_X} ${yCenter})`}
                    style={AXIS_TITLE_STYLE}
                >
                    {yTitle}
                </text>
            )}
        </svg>
    )
}
