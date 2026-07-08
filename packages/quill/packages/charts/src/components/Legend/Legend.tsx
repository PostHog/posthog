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
    const isVertical = orientation === 'vertical'
    // A vertical legend stacks from the start edge (justify-start) so it scrolls cleanly when it overflows
    // its slot — vertical packing is `align-content`, untouched here. Horizontal aligns via `justify-content`.
    const layout = isVertical
        ? 'flex-col gap-1 justify-start'
        : `flex-row flex-wrap gap-x-3 gap-y-1 ${JUSTIFY_CLASS[align]}`
    // No fixed max width — truncation is driven purely by the space actually available. Each row is bounded
    // to the legend's width (the full column when vertical, capped at the slot when horizontal) and the label
    // is the only shrinkable part, so a label ellipsizes only when its own row can't fit. Flexbox wraps rows
    // before shrinking them, so a multi-item horizontal legend additionally caps each row at half the line
    // (minus half the gap-x-3) — long labels pack at least two per line instead of one full-width row each.
    // A lone series keeps the full line and stays unclipped whenever it fits.
    const horizontalRowWidth = items.length > 1 ? 'inline-flex max-w-[calc(50%-0.375rem)]' : 'inline-flex max-w-full'
    const rowWidth = isVertical ? 'flex w-full' : horizontalRowWidth
    return (
        <div className={`flex ${layout} ${className ?? ''}`} data-attr={dataAttr}>
            {items.map((item) => {
                const dimmed = hidden?.has(item.key) ? ' opacity-40' : ''
                const rowClass = `${rowWidth} min-w-0 items-center gap-1.5 text-xs leading-none${dimmed}`
                const inner = (
                    <>
                        <span
                            aria-hidden="true"
                            className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                            style={{ backgroundColor: item.color }}
                        />
                        <span className="truncate min-w-0" title={item.label}>
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
