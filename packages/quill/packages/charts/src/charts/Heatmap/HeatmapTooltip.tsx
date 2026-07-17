import React from 'react'

import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import { findClosestSeriesKey } from '../../overlays/tooltipUtils'
import type { TooltipContext } from '../../core/types'

/** Meta attached to the adapter series the Heatmap hands to the base `Chart` — one series
 *  per row, carrying its row index so tooltip/click code can map back to the grid. */
export interface HeatmapRowMeta {
    rowIndex: number
}

/** Tooltip context handed to consumer-supplied `tooltip` callbacks — `TooltipContext` with
 *  the row meta baked in. Each `seriesData` entry is one row at the hovered column; use
 *  `findClosestSeriesKey(ctx.seriesData, ctx.hoverPosition.y)` (or this default tooltip)
 *  to narrow to the single hovered cell. */
export type HeatmapTooltipContext = TooltipContext<HeatmapRowMeta>

export interface HeatmapTooltipProps {
    ctx: HeatmapTooltipContext
    /** Formats the column (x) label shown in the header — e.g. ISO datetime → "Jun 24, 10:00". */
    labelFormatter?: (label: string) => React.ReactNode
    /** Formats the cell count. Defaults to `toLocaleString`. */
    valueFormatter?: (value: number) => React.ReactNode
}

/** Single-cell tooltip: the hovered column label, the hovered row's label, and that cell's
 *  count. The all-series-rows `DefaultTooltip` shape is wrong for a heatmap — a column has
 *  one row per y bucket, and only the one under the cursor matters. */
export function HeatmapTooltip({ ctx, labelFormatter, valueFormatter }: HeatmapTooltipProps): React.ReactElement | null {
    const { label, seriesData, hoverPosition } = ctx
    // Rows carry their cell's pixel range (yPixel = top, yPixelBottom = bottom), so containment
    // resolves the hovered cell exactly; the distance fallback covers the plot edges.
    const key = hoverPosition ? findClosestSeriesKey(seriesData, hoverPosition.y) : null
    const entry = key != null ? seriesData.find((s) => s.series.key === key) : undefined
    if (!entry) {
        return null
    }
    return (
        <TooltipSurface data-attr="hog-chart-tooltip">
            <div data-attr="hog-chart-tooltip-label" className="font-semibold mb-1 opacity-60">
                {labelFormatter ? labelFormatter(label) : label}
            </div>
            <div
                data-attr="hog-chart-tooltip-row"
                // eslint-disable-next-line react/forbid-dom-props
                style={{ display: 'flex', alignItems: 'center', gap: '0.375rem' }}
            >
                <TooltipSwatch color={entry.color} />
                <span data-attr="hog-chart-tooltip-series" className="truncate">
                    {entry.series.label}
                </span>
                <strong
                    data-attr="hog-chart-tooltip-value"
                    className="tabular-nums"
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ marginLeft: 'auto', paddingLeft: '0.75rem' }}
                >
                    {valueFormatter ? valueFormatter(entry.value) : entry.value.toLocaleString()}
                </strong>
            </div>
        </TooltipSurface>
    )
}
