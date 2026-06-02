/* eslint-disable react/forbid-dom-props -- swatch background-color is dynamic per item */
import React from 'react'

export interface LegendItem {
    key: string
    label: string
    color: string
}

export interface LegendProps {
    items: LegendItem[]
    orientation?: 'horizontal' | 'vertical'
    align?: 'start' | 'center' | 'end'
    onItemClick?: (key: string) => void
    hiddenKeys?: string[]
    className?: string
    dataAttr?: string
}

const ALIGN_CLASS = {
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
}: LegendProps): React.ReactElement | null {
    if (items.length === 0) {
        return null
    }
    const hidden = hiddenKeys?.length ? new Set(hiddenKeys) : null
    const layout = orientation === 'horizontal' ? 'flex-row flex-wrap gap-x-3 gap-y-1' : 'flex-col gap-1'
    return (
        <div className={`flex ${layout} ${ALIGN_CLASS[align]} ${className ?? ''}`} data-attr={dataAttr}>
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
                        <span className="truncate max-w-[200px]" title={item.label}>
                            {item.label}
                        </span>
                    </>
                )
                return onItemClick ? (
                    <button
                        key={item.key}
                        type="button"
                        className={`${rowClass} cursor-pointer bg-transparent border-0 p-0 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent`}
                        onClick={() => onItemClick(item.key)}
                    >
                        {inner}
                    </button>
                ) : (
                    <span key={item.key} className={rowClass}>
                        {inner}
                    </span>
                )
            })}
        </div>
    )
}
