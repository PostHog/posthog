import clsx from 'clsx'
import React from 'react'

import { CardMeta, Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { getDashboardTileDisplayName } from 'scenes/dashboard/dashboardUtils'
import { InsightErrorState } from 'scenes/insights/EmptyStates'

import { DashboardPlacement, DashboardTile } from '~/types'

interface DashboardErrorTileItemProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    tile: DashboardTile
    onRemove?: () => void
    onRetry?: () => void
    retryLoading?: boolean
    placement?: DashboardPlacement
    showEditingControls?: boolean
}

function DashboardErrorTileItemInternal(
    {
        tile,
        children,
        className,
        onRemove,
        onRetry,
        retryLoading,
        placement,
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
                moreButtons={
                    onRemove ? (
                        <LemonButton status="danger" onClick={onRemove} fullWidth>
                            Remove from dashboard
                        </LemonButton>
                    ) : undefined
                }
            />
            <InsightErrorState
                title="There is a problem loading this dashboard tile."
                onRetry={onRetry}
                retryLoading={retryLoading}
                placement={placement}
            />
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </div>
    )
}

export const DashboardErrorTileItem = React.forwardRef<HTMLDivElement, DashboardErrorTileItemProps>(
    DashboardErrorTileItemInternal
)
