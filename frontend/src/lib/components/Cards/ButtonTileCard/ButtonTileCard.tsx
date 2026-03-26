import '../CardMeta.scss'

import clsx from 'clsx'
import { useActions } from 'kea'
import { router } from 'kea-router'
import React from 'react'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

interface ButtonTileCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    buttonTile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    children?: JSX.Element
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: () => void
    moreButtonOverlay?: MoreProps['overlay']
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    /** Whether editing controls (three-dots menu) should be shown. False hides them on template dashboards in view mode. */
    showEditingControls?: boolean
    /** Suppresses button click navigation while the tile is being dragged. */
    isDraggingRef?: React.RefObject<boolean>
}

function ButtonTileCardInternal(
    {
        buttonTile: tile,
        showResizeHandles,
        children,
        className,
        moreButtonOverlay,
        placement,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        showEditingControls,
        isDraggingRef,
        ...divProps
    }: ButtonTileCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { button_tile } = tile
    const { push } = useActions(router)

    if (!button_tile) {
        throw new Error('ButtonTileCard requires button_tile')
    }

    const shouldHideMoreButton = placement === DashboardPlacement.Public || showEditingControls === false

    const handleClick = (): void => {
        if (isDraggingRef?.current) {
            return
        }
        if (button_tile.url.startsWith('/')) {
            push(button_tile.url)
        } else {
            try {
                const url = new URL(button_tile.url)
                if (url.protocol === 'http:' || url.protocol === 'https:') {
                    window.open(button_tile.url, '_blank', 'noopener,noreferrer')
                }
            } catch {
                // Invalid URL, do nothing
            }
        }
    }

    const isTransparent = tile.transparent_background

    return (
        <div
            className={clsx(
                'ButtonTileCard rounded flex flex-col',
                !isTransparent && 'bg-surface-primary border',
                isTransparent && showResizeHandles && 'border border-dashed border-border',
                className
            )}
            data-attr="button-tile-card"
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
                    'ButtonTileCard__body flex w-full flex-1 p-4 items-center',
                    !shouldHideMoreButton && 'pr-14',
                    button_tile.placement === 'right' ? 'md:justify-end' : 'justify-start',
                    onDragHandleMouseDown && 'cursor-grab'
                )}
                onMouseDown={onDragHandleMouseDown}
            >
                <LemonButton type={button_tile.style} onClick={handleClick} data-attr="button-tile-action">
                    {button_tile.text}
                </LemonButton>
            </div>

            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </div>
    )
}

export const ButtonTileCard = React.forwardRef<HTMLDivElement, ButtonTileCardProps>(ButtonTileCardInternal)
