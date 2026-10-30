import React from 'react'

import { ChartLegendLayout } from './ChartLegendLayout'
import { Legend, type LegendItem, type LegendProps } from './Legend'

export interface ChartLegendProps {
    /** When false, renders children with no wrapper and no legend. Defaults to true. */
    show?: boolean
    items: LegendItem[]
    position?: 'top' | 'bottom' | 'left' | 'right'
    align?: 'start' | 'center' | 'end'
    gap?: number
    onItemClick?: LegendProps['onItemClick']
    hiddenKeys?: string[]
    className?: string
    /** Wrap each legend row — forwarded to {@link Legend}'s `renderItem`. */
    renderItem?: (defaultNode: React.ReactNode, item: LegendItem) => React.ReactNode
    values?: LegendProps['values']
    formatValue?: LegendProps['formatValue']
    sortBy?: LegendProps['sortBy']
    sortDescending?: LegendProps['sortDescending']
    columnLabels?: LegendProps['columnLabels']
    /** data-attr on the inner `<Legend>`. The outer layout wrapper has no data-attr. */
    legendDataAttr?: string
    children: React.ReactNode
}

export function ChartLegend({
    show = true,
    items,
    position = 'top',
    align = 'center',
    gap,
    onItemClick,
    hiddenKeys,
    className,
    renderItem,
    values,
    formatValue,
    sortBy,
    sortDescending,
    columnLabels,
    legendDataAttr,
    children,
}: ChartLegendProps): React.ReactElement {
    if (!show || items.length === 0) {
        return <>{children}</>
    }
    const orientation = position === 'left' || position === 'right' ? 'vertical' : 'horizontal'
    // Bakes `flex-1 min-h-0` so consumers in a flex-col parent don't have to remember it.
    const wrapperClassName = `flex-1 min-h-0 ${className ?? ''}`.trim()
    return (
        <ChartLegendLayout
            legend={
                <Legend
                    items={items}
                    orientation={orientation}
                    align={align}
                    onItemClick={onItemClick}
                    hiddenKeys={hiddenKeys}
                    renderItem={renderItem}
                    values={values}
                    formatValue={formatValue}
                    sortBy={sortBy}
                    sortDescending={sortDescending}
                    columnLabels={columnLabels}
                    dataAttr={legendDataAttr}
                />
            }
            position={position}
            wide={!!values?.length}
            align={align}
            gap={gap}
            className={wrapperClassName}
        >
            {children}
        </ChartLegendLayout>
    )
}
