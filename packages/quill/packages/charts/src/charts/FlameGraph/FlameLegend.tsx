/* eslint-disable react/forbid-dom-props -- swatch colors come from the theme at runtime */
import React from 'react'

import type { FlameInk, FlameLegendEntry } from './flame-colors'

/** Groups past this count fold into one "+N more" entry, so a graph with many services keeps a
 *  one- or two-line legend. The largest groups come first. */
const MAX_ENTRIES = 12

function FlameLegendInner({ entries, ink }: { entries: FlameLegendEntry[]; ink: FlameInk }): React.ReactElement {
    const shown = entries.slice(0, MAX_ENTRIES)
    const rest = entries.length - shown.length
    return (
        <div className="flex flex-row flex-wrap gap-x-3 gap-y-1 text-xs leading-4 min-w-0">
            {shown.map((entry) => (
                <span key={entry.key} className="inline-flex items-center gap-1.5 min-w-0 max-w-[16rem]">
                    <span
                        aria-hidden="true"
                        className={`inline-block w-2.5 h-2.5 rounded-sm shrink-0 ${entry.dashed ? 'border border-dashed' : ''} ${entry.faded ? 'opacity-50' : ''}`}
                        style={{ backgroundColor: entry.color, borderColor: entry.dashed ? ink.ink : undefined }}
                    />
                    <span className="truncate min-w-0" title={entry.label} data-attr="hog-chart-legend-label">
                        {entry.label}
                    </span>
                    {entry.detail ? (
                        <span
                            className="shrink-0 tabular-nums text-(--color-graph-axis-label)"
                            data-attr="hog-chart-legend-secondary"
                        >
                            {entry.detail}
                        </span>
                    ) : null}
                </span>
            ))}
            {rest > 0 ? <span className="text-(--color-graph-axis-label)">+{rest} more</span> : null}
        </div>
    )
}

/** Memoized, because the chart re-renders on every mousemove while the legend only changes with the data. */
export const FlameLegend = React.memo(FlameLegendInner)
