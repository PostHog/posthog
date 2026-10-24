import React from 'react'

import { TooltipSurface, TooltipSwatch } from '../../overlays/TooltipSurface'
import { percentage } from '../../utils/format'
import type { HistogramTooltipContext } from './types'

export interface HistogramTooltipProps<Meta = unknown> {
    ctx: HistogramTooltipContext<Meta>
    /** Formats the bin edges. */
    formatX: (value: number) => string
    /** Formats counts. */
    formatCount: (value: number) => string
}

function formatShare(fraction: number): string {
    // Two decimals keep a tail bin's share distinguishable from zero.
    return percentage(fraction, fraction > 0 && fraction < 0.01 ? 2 : 1)
}

function Row({ label, value, swatch }: { label: string; value: string; swatch?: string }): React.ReactElement {
    return (
        <div data-attr="hog-chart-tooltip-row" className="flex items-center gap-2 min-w-0 py-0.5">
            {swatch && <TooltipSwatch color={swatch} />}
            <span data-attr="hog-chart-tooltip-series" className="flex-1 min-w-0 truncate opacity-60">
                {label}
            </span>
            <strong data-attr="hog-chart-tooltip-value" className="tabular-nums">
                {value}
            </strong>
        </div>
    )
}

/** Bin range, its count and share, the share below its upper edge, and one row per non-empty series
 *  when the bins are stacked. Reuses the shared tooltip `data-attr` hooks. */
export function HistogramTooltip<Meta = unknown>({
    ctx,
    formatX,
    formatCount,
}: HistogramTooltipProps<Meta>): React.ReactElement {
    const { bin, count, fraction, cumulativeFraction, seriesData } = ctx
    return (
        <TooltipSurface data-attr="hog-chart-histogram-tooltip">
            <div data-attr="hog-chart-tooltip-label" className="font-semibold mb-1 opacity-60 tabular-nums">
                {formatX(bin.start)} – {formatX(bin.end)}
            </div>
            <Row label="Count" value={`${formatCount(count)} (${formatShare(fraction)})`} />
            {/* Top of the stack first, matching the bar; a many-layer stack is mostly zeros in one bin. */}
            {seriesData.length > 1 &&
                [...seriesData]
                    .reverse()
                    .filter((entry) => entry.value > 0)
                    .map((entry) => (
                        <Row
                            key={entry.series.key}
                            label={entry.series.label}
                            value={formatCount(entry.value)}
                            swatch={entry.color}
                        />
                    ))}
            <div className="mt-1 pt-1 border-t border-current/25">
                <Row label={`Below ${formatX(bin.end)}`} value={formatShare(cumulativeFraction)} />
            </div>
        </TooltipSurface>
    )
}
