/* eslint-disable react/forbid-dom-props -- dynamic pixel gap from prop */
import React from 'react'

export interface ChartLegendLayoutProps {
    legend: React.ReactNode
    position?: 'top' | 'bottom' | 'left' | 'right'
    align?: 'start' | 'center' | 'end'
    gap?: number
    className?: string
    dataAttr?: string
    children: React.ReactNode
}

const ALIGN_CLASS = {
    start: 'items-start',
    center: 'items-center',
    end: 'items-end',
} as const

export function ChartLegendLayout({
    legend,
    position = 'top',
    align = 'center',
    gap = 8,
    className,
    dataAttr,
    children,
}: ChartLegendLayoutProps): React.ReactElement {
    const isRow = position === 'left' || position === 'right'
    const legendFirst = position === 'top' || position === 'left'
    // Bound the legend so a many-series legend scrolls instead of inflating the chart: a side legend
    // caps at the chart's height and ~45% of its width; a top/bottom legend caps at ~40% height so the
    // plot always keeps the majority. Needs the chart container to have a resolved cross-axis size.
    // Inline (not Tailwind classes) because the consuming app doesn't scan this package for utilities.
    const legendStyle: React.CSSProperties = isRow
        ? { maxHeight: '100%', maxWidth: '45%', overflowY: 'auto' }
        : { maxHeight: '40%', overflowY: 'auto' }
    const legendSlot = legend ? (
        <div className="flex-none shrink-0 min-h-0 min-w-0" style={legendStyle}>
            {legend}
        </div>
    ) : null
    // `flex flex-col` so the inner chart's `flex: 1` resolves; `self-stretch` so the chart fills the cross axis regardless of `align` (which then only affects the legend).
    const chartSlot = <div className="flex flex-col flex-1 min-w-0 min-h-0 self-stretch">{children}</div>
    return (
        <div
            className={`flex min-w-0 min-h-0 ${isRow ? 'flex-row' : 'flex-col'} ${ALIGN_CLASS[align]} ${className ?? ''}`}
            style={{ gap }}
            data-attr={dataAttr}
        >
            {legendFirst ? legendSlot : chartSlot}
            {legendFirst ? chartSlot : legendSlot}
        </div>
    )
}
