import React from 'react'

import { TooltipSurface } from '../../overlays/TooltipSurface'

export interface ScatterTooltipProps {
    label?: string | null
    xLabel?: string
    yLabel?: string
    xValue: React.ReactNode
    yValue: React.ReactNode
}

/** Default tooltip for {@link ScatterChart}: an optional point title plus the x/y readout.
 *  Reuses `DefaultTooltip`'s `data-attr` hooks so the shared testing accessors keep working. */
export function ScatterTooltip({ label, xLabel, yLabel, xValue, yValue }: ScatterTooltipProps): React.ReactElement {
    return (
        <TooltipSurface>
            {label && (
                <div data-attr="hog-chart-tooltip-label" className="font-semibold mb-1 opacity-60">
                    {label}
                </div>
            )}
            <div data-attr="hog-chart-tooltip-row" className="flex items-center gap-2 min-w-0 py-0.5">
                <span data-attr="hog-chart-tooltip-series" className="flex-1 opacity-60 truncate">
                    {xLabel || 'X'}
                </span>
                <strong data-attr="hog-chart-tooltip-value" className="tabular-nums">
                    {xValue}
                </strong>
            </div>
            <div data-attr="hog-chart-tooltip-row" className="flex items-center gap-2 min-w-0 py-0.5">
                <span data-attr="hog-chart-tooltip-series" className="flex-1 opacity-60 truncate">
                    {yLabel || 'Y'}
                </span>
                <strong data-attr="hog-chart-tooltip-value" className="tabular-nums">
                    {yValue}
                </strong>
            </div>
        </TooltipSurface>
    )
}
