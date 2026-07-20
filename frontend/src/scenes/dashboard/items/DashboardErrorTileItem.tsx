import clsx from 'clsx'
import React from 'react'

import { CardMeta, Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdge, EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { InsightErrorState } from 'scenes/insights/EmptyStates'

import { DashboardTile, QueryBasedInsightModel } from '~/types'

import { getDashboardTileDisplayName } from '../dashboardUtils'

interface DashboardErrorTileItemProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    tile: DashboardTile<QueryBasedInsightModel>
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    onRemove?: () => void
    showEditingControls?: boolean
}

function DashboardErrorTileItemInternal(
    {
        tile,
        canEnterEditModeFromEdge,
        children,
        className,
        onDragHandleMouseDown,
        onEnterEditModeFromEdge,
        onRemove,
        showEditingControls,
        showResizeHandles,
        ...divProps
    }: DashboardErrorTileItemProps,
    ref: React.ForwardedRef<HTMLDivElement>
): JSX.Element {
    return (
        <div
            className={clsx('DashboardTileCard InsightCard border', className)}
            data-attr="dashboard-tile-error"
            ref={ref}
            {...divProps}
        >
            <CardMeta
                topHeading={<span>{getDashboardTileDisplayName(tile)}</span>}
                showEditingControls={showEditingControls}
                onMouseDown={onDragHandleMouseDown}
                moreButtons={
                    onRemove ? (
                        <LemonButton status="danger" onClick={onRemove} fullWidth>
                            Remove from dashboard
                        </LemonButton>
                    ) : undefined
                }
            />
            <InsightErrorState title="There is a problem loading this dashboard tile." supportOnly />
            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </div>
    )
}

export const DashboardErrorTileItem = React.forwardRef<HTMLDivElement, DashboardErrorTileItemProps>(
    DashboardErrorTileItemInternal
)
