import React from 'react'

export function LegendTag({ tag }: { tag: string }): React.ReactElement {
    return (
        <span
            className="shrink-0 rounded-full border border-(--color-graph-axis-line) px-1.5 text-[10px] leading-3.5 text-(--color-graph-axis-label)"
            data-attr="hog-chart-legend-tag"
        >
            {tag}
        </span>
    )
}
