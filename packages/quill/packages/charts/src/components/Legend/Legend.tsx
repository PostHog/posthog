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

// Position a horizontal legend via auto-margins on a fit-content box, not `justify-content`: rows keep a
// shared left edge (so a wrapped legend is a clean grid, not ragged) while the block still honors `align`.
const BLOCK_ALIGN_CLASS = {
    start: 'mr-auto',
    center: 'mx-auto',
    end: 'ml-auto',
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
    // Stack from the start edge (justify-start) so the legend scrolls cleanly when it overflows its slot;
    // centering would push the leading rows past the scroll origin. Horizontal adds the fit-content box.
    const layout =
        orientation === 'horizontal'
            ? `flex-row flex-wrap gap-x-3 gap-y-1 justify-start w-fit max-w-full ${BLOCK_ALIGN_CLASS[align]}`
            : 'flex-col gap-1 justify-start'
    return (
        <div className={`flex ${layout} ${className ?? ''}`} data-attr={dataAttr}>
            {items.map((item) => {
                const dimmed = hidden?.has(item.key) ? ' opacity-40' : ''
                const rowClass = `inline-flex items-center gap-1.5 text-xs leading-none${dimmed}`
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
