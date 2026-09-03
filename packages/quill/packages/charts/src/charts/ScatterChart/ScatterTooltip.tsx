import React from 'react'

import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import type { ScatterPointDatum } from './types'

export interface ScatterTooltipProps<Meta = unknown> {
    point: ScatterPointDatum<Meta>
    header?: React.ReactNode
    xLabel?: string
    yLabel?: string
    xValue?: React.ReactNode
    yValue?: React.ReactNode
}

function Row({ label, value }: { label: string; value: React.ReactNode }): React.ReactElement {
    return (
        <div data-attr="hog-chart-tooltip-row" className="flex items-center gap-2 min-w-0 py-0.5">
            <span data-attr="hog-chart-tooltip-series" className="flex-1 min-w-0 truncate opacity-60">
                {label}
            </span>
            <strong data-attr="hog-chart-tooltip-value" className="tabular-nums">
                {value}
            </strong>
        </div>
    )
}

/** `DefaultTooltip` can't serve, because its rows are series values at one x-axis label, whereas a
 *  scatter point *is* the reading. Its `data-attr` hooks are reused, so the shared tooltip test
 *  accessor reads this one too. */
export function ScatterTooltip<Meta = unknown>({
    point,
    header,
    xLabel,
    yLabel,
    xValue,
    yValue,
}: ScatterTooltipProps<Meta>): React.ReactElement {
    // The y row names the measure, so the series label serves when the axis is untitled — a chart
    // whose y axis holds one column per series has that name nowhere else.
    const yRowLabel = yLabel || point.seriesLabel || 'Y'
    const title = header ?? point.label ?? point.seriesLabel
    const showTitle = Boolean(title) && title !== yRowLabel
    return (
        <TooltipSurface>
            {showTitle ? (
                <div
                    data-attr="hog-chart-tooltip-label"
                    className="flex items-center gap-2 min-w-0 font-semibold mb-1 opacity-60"
                >
                    <TooltipSwatch color={point.color} />
                    <span className="truncate">{title}</span>
                </div>
            ) : null}
            <Row label={xLabel || 'X'} value={xValue ?? point.x.toLocaleString()} />
            <Row label={yRowLabel} value={yValue ?? point.y.toLocaleString()} />
        </TooltipSurface>
    )
}
