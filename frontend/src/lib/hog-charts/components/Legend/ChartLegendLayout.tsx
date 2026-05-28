/* eslint-disable react/forbid-dom-props -- dynamic pixel gap from prop */
import React from 'react'

export interface ChartLegendLayoutProps {
    /** The legend element. Anything that renders is allowed (typically a `<Legend />`).
     *  Falsy values (`null`, `undefined`, `false`) omit the legend slot entirely. */
    legend: React.ReactNode
    /** Side of the chart on which to place the legend. Defaults to `'top'`. */
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** Cross-axis alignment of the legend slot relative to the chart. Defaults to `'center'`. */
    align?: 'start' | 'center' | 'end'
    /** Pixels between the legend slot and the chart. Defaults to `8`. */
    gap?: number
    className?: string
    dataAttr?: string
    /** The chart (or anything that should fill the remaining space). */
    children: React.ReactNode
}

const ALIGN_ROW_CLASS: Record<NonNullable<ChartLegendLayoutProps['align']>, string> = {
    start: 'items-start',
    center: 'items-center',
    end: 'items-end',
}

const ALIGN_COL_CLASS: Record<NonNullable<ChartLegendLayoutProps['align']>, string> = {
    start: 'items-start',
    center: 'items-center',
    end: 'items-end',
}

export function ChartLegendLayout({
    legend,
    position = 'top',
    align = 'center',
    gap = 8,
    className,
    dataAttr,
    children,
}: ChartLegendLayoutProps): React.ReactElement {
    const isHorizontal = position === 'left' || position === 'right'
    const legendBefore = position === 'top' || position === 'left'
    const containerClass = [
        'flex min-w-0 min-h-0',
        isHorizontal ? 'flex-row' : 'flex-col',
        isHorizontal ? ALIGN_ROW_CLASS[align] : ALIGN_COL_CLASS[align],
        className ?? '',
    ]
        .filter(Boolean)
        .join(' ')

    const legendSlot = legend ? (
        <div className="flex-none shrink-0" data-attr="hog-charts-legend-slot">
            {legend}
        </div>
    ) : null
    const chartSlot = (
        <div className="flex-1 min-w-0 min-h-0" data-attr="hog-charts-chart-slot">
            {children}
        </div>
    )

    return (
        <div className={containerClass} style={{ gap }} data-attr={dataAttr}>
            {legendBefore ? legendSlot : chartSlot}
            {legendBefore ? chartSlot : legendSlot}
        </div>
    )
}
