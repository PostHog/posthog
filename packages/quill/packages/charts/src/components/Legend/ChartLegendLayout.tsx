/* eslint-disable react/forbid-dom-props -- dynamic pixel gap from prop */
import React from 'react'

export interface ChartLegendLayoutProps {
    legend: React.ReactNode
    position?: 'top' | 'bottom' | 'left' | 'right'
    align?: 'start' | 'center' | 'end'
    gap?: number
    className?: string
    dataAttr?: string
    /** Give a side legend more width, for a legend with value columns. */
    wide?: boolean
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
    wide = false,
    children,
}: ChartLegendLayoutProps): React.ReactElement {
    const isRow = position === 'left' || position === 'right'
    const legendFirst = position === 'top' || position === 'left'
    // Side legends stretch to the chart height — a % max-height no-ops without an explicit ancestor height,
    // which top/bottom's max-h-[40%] still needs. Their width caps at 45% of the chart but never more than
    // 240px, so one long label can't squeeze the plot on a wide chart. `justify-center-safe` keeps short
    // side legends centered yet scrollable (plain center would push the top rows past the scroll origin).
    // A side table legend needs room for its value columns, so it moves below (or above) a chart
    // narrower than 480px rather than squeezing the plot and the series names.
    const stackWhenNarrow = isRow && wide
    const legendClass = isRow
        ? `flex flex-col self-stretch ${wide ? 'max-w-[min(60%,480px)] @max-[480px]:max-w-none @max-[480px]:max-h-[40%]' : 'max-w-[min(45%,240px)]'} overflow-y-auto justify-center-safe`
        : 'self-stretch max-h-[40%] overflow-y-auto'

    const legendSlot = legend ? (
        <div className={`flex-none shrink-0 min-h-0 min-w-0 ${legendClass}`}>{legend}</div>
    ) : null
    // `flex flex-col` so the inner chart's `flex: 1` resolves; `self-stretch` so the chart fills the cross axis regardless of `align` (which then only affects the legend).
    const chartSlot = <div className="flex flex-col flex-1 min-w-0 min-h-0 self-stretch">{children}</div>
    const layout = (
        <div
            className={`flex min-w-0 min-h-0 ${isRow ? 'flex-row' : 'flex-col'} ${stackWhenNarrow ? 'flex-1 @max-[480px]:flex-col' : ''} ${ALIGN_CLASS[align]} ${stackWhenNarrow ? '' : (className ?? '')}`}
            style={{ gap }}
            data-attr={stackWhenNarrow ? undefined : dataAttr}
        >
            {legendFirst ? legendSlot : chartSlot}
            {legendFirst ? chartSlot : legendSlot}
        </div>
    )
    // The container query reads the width of a wrapper, since an element can't query its own size.
    return stackWhenNarrow ? (
        <div className={`@container flex min-w-0 min-h-0 ${className ?? ''}`} data-attr={dataAttr}>
            {layout}
        </div>
    ) : (
        layout
    )
}
