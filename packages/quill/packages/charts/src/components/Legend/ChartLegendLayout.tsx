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
    // Side legends stretch to the chart height — a % max-height no-ops without an explicit ancestor height,
    // which top/bottom's max-h-[40%] still needs. `justify-center-safe` keeps short side legends centered
    // yet scrollable (plain center would push the top rows past the scroll origin).
    const legendClass = isRow
        ? 'flex flex-col self-stretch max-w-[45%] overflow-y-auto justify-center-safe'
        : 'self-stretch max-h-[40%] overflow-y-auto'

    const legendSlot = legend ? (
        <div className={`flex-none shrink-0 min-h-0 min-w-0 ${legendClass}`}>{legend}</div>
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
