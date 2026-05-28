/* eslint-disable react/forbid-dom-props -- swatch background-color is dynamic per item */
import React from 'react'

export interface LegendItem {
    /** Stable identifier — typically matches a `Series.key`. */
    key: string
    /** Display text shown next to the swatch. */
    label: string
    /** CSS color string for the swatch (hex, rgb, var(--…), etc.). */
    color: string
}

export interface LegendProps {
    items: LegendItem[]
    /** Layout direction. Defaults to `'horizontal'`. */
    orientation?: 'horizontal' | 'vertical'
    /** Main-axis alignment of items within the legend container. Defaults to `'center'`. */
    align?: 'start' | 'center' | 'end'
    /** When provided, items render as `<button>` elements that fire this callback with the item's key. */
    onItemClick?: (key: string) => void
    /** Item keys that should render dimmed (e.g. hidden / excluded series). */
    hiddenKeys?: string[]
    className?: string
    dataAttr?: string
}

const ALIGN_CLASS: Record<NonNullable<LegendProps['align']>, string> = {
    start: 'justify-start',
    center: 'justify-center',
    end: 'justify-end',
}

export function Legend({
    items,
    orientation = 'horizontal',
    align = 'center',
    onItemClick,
    hiddenKeys,
    className,
    dataAttr,
}: LegendProps): React.ReactElement | null {
    if (items.length === 0) {
        return null
    }
    const hidden = hiddenKeys && hiddenKeys.length > 0 ? new Set(hiddenKeys) : null
    const containerClass = [
        'flex',
        orientation === 'horizontal' ? 'flex-row flex-wrap gap-x-3 gap-y-1' : 'flex-col gap-1',
        ALIGN_CLASS[align],
        className ?? '',
    ]
        .filter(Boolean)
        .join(' ')

    return (
        <div className={containerClass} data-attr={dataAttr}>
            {items.map((item) => {
                const isHidden = hidden?.has(item.key) ?? false
                const rowClass = ['inline-flex items-center gap-1.5 text-xs leading-none', isHidden ? 'opacity-40' : '']
                    .filter(Boolean)
                    .join(' ')
                const swatch = (
                    <span
                        aria-hidden="true"
                        className="inline-block w-2.5 h-2.5 rounded-sm shrink-0"
                        style={{ backgroundColor: item.color }}
                    />
                )
                const label = <span className="truncate">{item.label}</span>
                if (onItemClick) {
                    return (
                        <button
                            key={item.key}
                            type="button"
                            className={`${rowClass} cursor-pointer bg-transparent border-0 p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
                            onClick={() => onItemClick(item.key)}
                            data-attr={`hog-charts-legend-item-${item.key}`}
                        >
                            {swatch}
                            {label}
                        </button>
                    )
                }
                return (
                    <span key={item.key} className={rowClass} data-attr={`hog-charts-legend-item-${item.key}`}>
                        {swatch}
                        {label}
                    </span>
                )
            })}
        </div>
    )
}
