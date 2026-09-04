import React from 'react'

import { ChartLegendLayout } from './ChartLegendLayout'
import { Legend, type LegendItem, type LegendProps } from './Legend'

export interface ChartLegendProps {
    /** When false, renders children with no wrapper and no legend. Defaults to true. */
    show?: boolean
    items: LegendItem[]
    position?: 'top' | 'bottom' | 'left' | 'right'
    /** Position to lay out at instead of `position` — e.g. a chart moving a side legend below the
     *  plot because the container got narrow. The rows re-orient to match. */
    effectivePosition?: 'top' | 'bottom' | 'left' | 'right'
    align?: 'start' | 'center' | 'end'
    gap?: number
    onItemClick?: LegendProps['onItemClick']
    hiddenKeys?: string[]
    className?: string
    /** Wrap each legend row — forwarded to {@link Legend}'s `renderItem`. */
    renderItem?: (defaultNode: React.ReactNode, item: LegendItem) => React.ReactNode
    /** data-attr on the inner `<Legend>`. The outer layout wrapper has no data-attr. */
    legendDataAttr?: string
    children: React.ReactNode
}

export const ChartLegend = React.forwardRef<HTMLDivElement, ChartLegendProps>(function ChartLegend(
    {
        show = true,
        items,
        position = 'top',
        effectivePosition,
        align = 'center',
        gap,
        onItemClick,
        hiddenKeys,
        className,
        renderItem,
        legendDataAttr,
        children,
    },
    ref
): React.ReactElement {
    if (!show || items.length === 0) {
        return <>{children}</>
    }
    const resolved = effectivePosition ?? position
    const orientation = resolved === 'left' || resolved === 'right' ? 'vertical' : 'horizontal'
    // Bakes `flex-1 min-h-0` so consumers in a flex-col parent don't have to remember it.
    const wrapperClassName = `flex-1 min-h-0 ${className ?? ''}`.trim()
    return (
        <ChartLegendLayout
            ref={ref}
            legend={
                <Legend
                    items={items}
                    orientation={orientation}
                    align={align}
                    onItemClick={onItemClick}
                    hiddenKeys={hiddenKeys}
                    renderItem={renderItem}
                    dataAttr={legendDataAttr}
                />
            }
            position={position}
            effectivePosition={effectivePosition}
            align={align}
            gap={gap}
            className={wrapperClassName}
        >
            {children}
        </ChartLegendLayout>
    )
})
