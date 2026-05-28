import React from 'react'

import { ChartLegendLayout } from './ChartLegendLayout'
import { Legend, type LegendItem } from './Legend'

export interface ChartLegendProps {
    /** When false, renders children with no wrapper and no legend. Defaults to true. */
    show?: boolean
    items: LegendItem[]
    position?: 'top' | 'bottom' | 'left' | 'right'
    align?: 'start' | 'center' | 'end'
    gap?: number
    onItemClick?: (key: string) => void
    hiddenKeys?: string[]
    className?: string
    dataAttr?: string
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
    dataAttr,
    children,
}: ChartLegendProps): React.ReactElement {
    if (!show || items.length === 0) {
        return <>{children}</>
    }
    const orientation = position === 'left' || position === 'right' ? 'vertical' : 'horizontal'
    // Charts inside expect the wrapper to claim its parent's flex height — bake `flex-1 min-h-0`
    // in so consumers don't have to remember it. Caller-supplied className still wins (appended).
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
                    dataAttr={dataAttr}
                />
            }
            position={position}
            align={align}
            gap={gap}
            className={wrapperClassName}
        >
            {children}
        </ChartLegendLayout>
    )
}
