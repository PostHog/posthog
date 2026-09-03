import clsx from 'clsx'
import React from 'react'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdge, EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

import { separatorTileThicknessClassName, type SeparatorTileThickness } from './separatorTileUtils'

interface DashboardSeparatorTileProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    tile: DashboardTile<QueryBasedInsightModel>
    thickness: SeparatorTileThickness
    placement: DashboardPlacement
    children?: JSX.Element
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    moreButtonOverlay?: MoreProps['overlay']
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    showEditingControls?: boolean
}

function DashboardSeparatorTileInternal(
    {
        thickness,
        showResizeHandles,
        children,
        className,
        moreButtonOverlay,
        placement,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        showEditingControls,
        ...divProps
    }: DashboardSeparatorTileProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const shouldHideMoreButton = placement === DashboardPlacement.Public || showEditingControls === false
    const thicknessClassName = separatorTileThicknessClassName(thickness)

    return (
        <div
            className={clsx(
                'DashboardTileCard DashboardSeparatorTile relative flex h-full flex-col',
                showResizeHandles && 'border border-dashed border-border',
                className
            )}
            data-attr="separator-tile"
            {...divProps}
            ref={ref}
        >
            {moreButtonOverlay && !shouldHideMoreButton && (
                <div className="absolute right-4 top-4">
                    <More overlay={moreButtonOverlay} />
                </div>
            )}
            <div
                className={clsx(
                    'DashboardTileCard__body SeparatorTile__body flex flex-1 items-center px-4',
                    onDragHandleMouseDown && 'cursor-grab'
                )}
                onMouseDown={onDragHandleMouseDown}
            >
                <hr className={clsx('m-0 w-full border-0 bg-border', thicknessClassName)} />
            </div>
            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </div>
    )
}

export const DashboardSeparatorTile = React.forwardRef<HTMLDivElement, DashboardSeparatorTileProps>(
    DashboardSeparatorTileInternal
)
