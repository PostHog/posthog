import React, { useMemo } from 'react'

import { useChartLayout } from '../../core/chart-context'
import { mixColors, perceivedLuminance } from '../../core/color-utils'
import { FONT_FAMILY, measureLabelWidth } from '../../utils/text-measure'
import type { HeatmapCellDatum } from './Heatmap'
import { cellAlpha, cellRect, computeHeatmapLayout, normalizeCount, type HeatmapColorScale } from './heatmap-layout'

/** Returning null or an empty string leaves the cell unlabelled. */
export type HeatmapCellLabelFormatter = (cell: HeatmapCellDatum) => string | null

const LABEL_FONT_SIZE = 12
const LABEL_FONT = `500 ${LABEL_FONT_SIZE}px ${FONT_FAMILY}`
const LABEL_PADDING_X = 4
// Under this the text touches the cell edges and reads as one smear across rows.
const MIN_CELL_HEIGHT = LABEL_FONT_SIZE + 4
// A cell fill this light keeps dark text; above it the fill is dark enough for white text.
const DARK_FILL_LUMINANCE = 0.55

const LABEL_STYLE_BASE: React.CSSProperties = {
    position: 'absolute',
    transform: 'translate(-50%, -50%)',
    fontSize: LABEL_FONT_SIZE,
    fontWeight: 500,
    lineHeight: 1,
    pointerEvents: 'none',
    whiteSpace: 'nowrap',
}

interface PlacedLabel {
    key: string
    text: string
    x: number
    y: number
    color: string
}

export interface HeatmapCellLabelsProps {
    xLabels: string[]
    yLabels: string[]
    /** Dense grid, `cells[rowIndex][colIndex]` — the same grid the canvas draws. */
    cells: number[][]
    accent: string
    maxValue: number
    colorScale: HeatmapColorScale
    formatter: HeatmapCellLabelFormatter
}

/** DOM labels centered in each heatmap cell. Text stays DOM rather than canvas for the same
 *  reason the axis labels do: crisp type, and one place that owns font and color. */
export function HeatmapCellLabels({
    xLabels,
    yLabels,
    cells,
    accent,
    maxValue,
    colorScale,
    formatter,
}: HeatmapCellLabelsProps): React.ReactElement | null {
    const { dimensions, theme } = useChartLayout()

    const placed = useMemo<PlacedLabel[]>(() => {
        const layout = computeHeatmapLayout(dimensions, xLabels.length, yLabels.length)
        if (layout.rowHeight < MIN_CELL_HEIGHT || layout.colWidth <= 0) {
            return []
        }
        const background = theme.backgroundColor ?? '#ffffff'
        const darkText = theme.axisColor ?? '#111111'
        const maxTextWidth = layout.colWidth - LABEL_PADDING_X * 2
        const out: PlacedLabel[] = []
        for (let row = 0; row < layout.rows; row++) {
            for (let col = 0; col < layout.cols; col++) {
                const value = cells[row]?.[col] ?? 0
                const text = formatter({
                    xIndex: col,
                    yIndex: row,
                    xLabel: xLabels[col] ?? '',
                    yLabel: yLabels[row] ?? '',
                    value,
                })
                if (!text || measureLabelWidth(text, LABEL_FONT) > maxTextWidth) {
                    continue
                }
                // The canvas paints the accent at `cellAlpha` over the plot background, and a
                // linear mix by that alpha is exactly that composite, so the text contrasts
                // against the color the reader sees instead of the accent at full strength.
                const fill =
                    value > 0
                        ? mixColors(background, accent, cellAlpha(normalizeCount(value, maxValue, colorScale)))
                        : background
                const rect = cellRect(layout, col, row)
                out.push({
                    key: `${row}:${col}`,
                    text,
                    x: rect.x + rect.width / 2,
                    y: rect.y + rect.height / 2,
                    color: perceivedLuminance(fill) < DARK_FILL_LUMINANCE ? '#ffffff' : darkText,
                })
            }
        }
        return out
    }, [dimensions, theme, xLabels, yLabels, cells, accent, maxValue, colorScale, formatter])

    if (placed.length === 0) {
        return null
    }

    return (
        <>
            {placed.map((label) => (
                <div
                    key={label.key}
                    data-attr="hog-chart-heatmap-cell-label"
                    style={{ ...LABEL_STYLE_BASE, left: label.x, top: label.y, color: label.color }}
                >
                    {label.text}
                </div>
            ))}
        </>
    )
}
