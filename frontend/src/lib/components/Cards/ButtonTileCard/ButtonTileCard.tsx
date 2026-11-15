import '../CardMeta.scss'

import clsx from 'clsx'
import { useActions } from 'kea'
import { router } from 'kea-router'
import React from 'react'

import { Button } from '@posthog/quill'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardTileShell } from 'lib/components/Cards/DashboardTileShell'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { QuillCardMoreMenu } from 'lib/components/Cards/QuillCardMoreMenu'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { quillButtonVariant } from 'lib/lemon-ui/LemonButton/quillButtonVariant'

import { DashboardPlacement, DashboardTile } from '~/types'

interface ButtonTileCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    buttonTile: DashboardTile
    placement: DashboardPlacement
    children?: JSX.Element
    moreButtonOverlay?: MoreProps['overlay']
    /** Quill rows for the "more" menu, shown instead of `moreButtonOverlay`. */
    quillMenuItems?: JSX.Element
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
        quillMenuItems,
        placement,
        showEditingControls,
        isDraggingRef,
        ...divProps
    }: ButtonTileCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { button_tile } = tile
    const { push } = useActions(router)
    const todayRailNav = useFeatureFlag('TODAY_RAIL_NAV')

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
        <DashboardTileShell
            transparent={isTransparent}
            showResizeHandles={showResizeHandles}
            className={clsx('DashboardTileCard ButtonTileCard flex flex-col', className)}
            data-attr="button-tile-card"
            {...divProps}
            ref={ref}
        >
            {(quillMenuItems || moreButtonOverlay) && !shouldHideMoreButton && (
                <div className="absolute right-4 top-4">
                    {quillMenuItems ? (
                        <QuillCardMoreMenu items={quillMenuItems} />
                    ) : (
                        <More overlay={moreButtonOverlay} />
                    )}
                </div>
            )}

            <div
                className={clsx(
                    'DashboardTileCard__body ButtonTileCard__body flex w-full flex-1 p-4 items-center',
                    !shouldHideMoreButton && 'pr-14',
                    button_tile.placement === 'right' ? 'md:justify-end' : 'justify-start'
                )}
            >
                {todayRailNav ? (
                    <Button
                        variant={quillButtonVariant(button_tile.style)}
                        onClick={handleClick}
                        data-attr="button-tile-action"
                    >
                        {button_tile.text}
                    </Button>
                ) : (
                    <LemonButton type={button_tile.style} onClick={handleClick} data-attr="button-tile-action">
                        {button_tile.text}
                    </LemonButton>
                )}
            </div>

            {showResizeHandles && <DashboardResizeHandles />}
            {children}
        </DashboardTileShell>
    )
}

export const ButtonTileCard = React.forwardRef<HTMLDivElement, ButtonTileCardProps>(ButtonTileCardInternal)
