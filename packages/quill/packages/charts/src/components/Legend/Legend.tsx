/* eslint-disable react/forbid-dom-props -- swatch background-color is dynamic per item */
import React from 'react'

export interface LegendItem {
    key: string
    label: string
    color: string
    /** Optional trailing text shown muted after the label — e.g. a slope chart's per-series change. */
    secondaryLabel?: string
}

export interface LegendProps {
    items: LegendItem[]
    orientation?: 'horizontal' | 'vertical'
    align?: 'start' | 'center' | 'end'
    onItemClick?: (key: string) => void
    hiddenKeys?: string[]
    className?: string
    dataAttr?: string
    /** Wrap each row — receives the default row node and its item, returns the node to render.
     *  Use to augment rows (e.g. a right-click context menu) while keeping the default rendering. */
    renderItem?: (defaultNode: React.ReactNode, item: LegendItem) => React.ReactNode
}

// Align a horizontal legend with `justify-content` so wrapped rows stay centered (or start/end) within the
// full-width slot. A fit-content + auto-margin box can't center once it wraps — `width: fit-content` on a
// wrapping flex container collapses to the slot width, leaving the rows pinned to the start edge.
const JUSTIFY_CLASS = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
} as const

export function Legend({
    items,
    orientation = 'horizontal',
    align = 'center',
    onItemClick,
    hiddenKeys,
    className,
    dataAttr,
    renderItem,
}: LegendProps): React.ReactElement | null {
    if (items.length === 0) {
        return null
    }
    const hidden = hiddenKeys?.length ? new Set(hiddenKeys) : null
    // A vertical legend stacks from the start edge (justify-start) so it scrolls cleanly when it overflows
    // its slot — vertical packing is `align-content`, untouched here. Horizontal aligns via `justify-content`.
    const layout =
        orientation === 'horizontal'
            ? `flex-row flex-wrap gap-x-3 gap-y-1 ${JUSTIFY_CLASS[align]}`
            : 'flex-col gap-1 justify-start'
    return (
        <div className={`flex ${layout} ${className ?? ''}`} data-attr={dataAttr}>
            {items.map((item) => {
                const dimmed = hidden?.has(item.key) ? ' opacity-40' : ''
                // leading-4 (not leading-none): the line box must contain descenders — the layout slot
                // wrapping the legend is a scroll container, which clips glyphs that poke below the line box.
                const rowClass = `inline-flex items-center gap-1.5 text-xs leading-4${dimmed}`
                const inner = (
                    <>
                        <span
                            aria-hidden="true"
                            className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                            style={{ backgroundColor: item.color }}
                        />
                        <span className="truncate" style={{ maxWidth: 180 }} title={item.label}>
                            {item.label}
                        </span>
                        {item.secondaryLabel != null && item.secondaryLabel !== '' && (
                            <span className="shrink-0 text-muted" data-attr="hog-chart-legend-secondary">
                                {item.secondaryLabel}
                            </span>
                        )}
                    </>
                )
                const node = onItemClick ? (
                    <button
                        type="button"
                        className={`${rowClass} cursor-pointer bg-transparent border-0 p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
                        onClick={() => onItemClick(item.key)}
                    >
                        {inner}
                    </button>
                ) : (
                    <span className={rowClass}>{inner}</span>
                )
                return <React.Fragment key={item.key}>{renderItem ? renderItem(node, item) : node}</React.Fragment>
            })}
        </div>
    )
}
