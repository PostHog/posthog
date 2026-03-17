import './ButtonTileCard.scss'

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
        ...divProps
    }: ButtonTileCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { button_tile } = tile
    const { push } = useActions(router)

    if (!button_tile) {
        throw new Error('ButtonTileCard requires button_tile')
    }

    const shouldHideMoreButton = placement === DashboardPlacement.Public

    const handleClick = (): void => {
        if (button_tile.url.startsWith('/')) {
            push(button_tile.url)
        } else {
            window.open(button_tile.url, '_blank', 'noopener,noreferrer')
        }
    }

    const isTransparent = tile.transparent_background

    return (
        <div
            className={clsx(
                'ButtonTileCard rounded flex flex-col h-full',
                !isTransparent && 'bg-surface-primary border',
                className
            )}
            data-attr="button-tile-card"
            {...divProps}
            ref={ref}
        >
            {moreButtonOverlay && !shouldHideMoreButton && (
                <div className="absolute right-4 top-4 z-10">
                    <More overlay={moreButtonOverlay} />
                </div>
            )}

            <div
                className={clsx(
                    'ButtonTileCard__body w-full p-4 pr-14',
                    button_tile.placement === 'right' ? 'justify-end' : 'justify-start',
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
