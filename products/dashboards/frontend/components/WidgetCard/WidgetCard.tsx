import clsx from 'clsx'
import React from 'react'

import 'lib/components/Cards/CardMeta.scss'
import type { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdge, EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'

type WidgetCardProps = React.HTMLAttributes<HTMLDivElement> &
    Resizeable & {
        canEnterEditModeFromEdge?: boolean
        onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
        /** RGL-injected resize handle nodes — rendered after decorative handles (see InsightCard). */
        gridChildren?: React.ReactNode
        children?: React.ReactNode
    }

export const WidgetCard = React.forwardRef<HTMLDivElement, WidgetCardProps>(function WidgetCard(
    {
        showResizeHandles,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        gridChildren,
        children,
        className,
        style,
        ...divProps
    },
    ref
): JSX.Element {
    return (
        <div
            data-slot="widget-card"
            className={clsx(
                'DashboardTileCard WidgetCard dashboard-widget-card min-h-0 rounded flex flex-col bg-surface-primary border',
                className
            )}
            {...divProps}
            style={style}
            ref={ref}
        >
            {children}
            {showResizeHandles && <DashboardResizeHandles />}
            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {gridChildren}
        </div>
    )
})
