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
    const legendSlot = legend ? <div className="flex-none shrink-0">{legend}</div> : null
    const chartSlot = <div className="flex-1 min-w-0 min-h-0">{children}</div>
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
