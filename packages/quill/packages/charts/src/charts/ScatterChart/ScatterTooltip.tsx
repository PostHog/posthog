import React from 'react'

import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import type { ScatterPointDatum } from './types'

export interface ScatterTooltipProps<Meta = unknown> {
    point: ScatterPointDatum<Meta>
    /** Overrides the header. Defaults to the point's label, falling back to its series label. */
    header?: React.ReactNode
    /** Row label for the x readout. Defaults to 'X'. */
    xLabel?: string
    /** Row label for the y readout. Defaults to 'Y'. */
    yLabel?: string
    /** Preformatted x value. Defaults to the raw number, locale-formatted. */
    xValue?: React.ReactNode
    /** Preformatted y value. Defaults to the raw number, locale-formatted. */
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

/** Default tooltip for {@link ScatterChart}: which point this is, then its two coordinates.
 *
 *  `DefaultTooltip` can't serve here — its rows are series values at an x-axis label, whereas a
 *  scatter point *is* the reading and both of its axes matter. The `data-attr` hooks are the same
 *  ones, so `createDefaultTooltipAccessor` reads this tooltip too. */
export function ScatterTooltip<Meta = unknown>({
    point,
    header,
    xLabel,
    yLabel,
    xValue,
    yValue,
}: ScatterTooltipProps<Meta>): React.ReactElement {
    const title = header ?? point.label ?? point.seriesLabel
    return (
        <TooltipSurface>
            {title ? (
                <div
                    data-attr="hog-chart-tooltip-label"
                    className="flex items-center gap-2 min-w-0 font-semibold mb-1 opacity-60"
                >
                    <TooltipSwatch color={point.color} />
                    <span className="truncate">{title}</span>
                </div>
            ) : null}
            <Row label={xLabel || 'X'} value={xValue ?? point.x.toLocaleString()} />
            <Row label={yLabel || 'Y'} value={yValue ?? point.y.toLocaleString()} />
        </TooltipSurface>
    )
}
