import clsx from 'clsx'
import React from 'react'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdge, EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonModal } from 'lib/lemon-ui/LemonModal'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

import { imageTilePositionToCss } from './imageTileUtils'
import type { ImageTileImage } from './imageTileUtils'

interface DashboardImageTileProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    tile: DashboardTile<QueryBasedInsightModel>
    image: ImageTileImage
    placement: DashboardPlacement
    children?: JSX.Element
    canEnterEditModeFromEdge?: boolean
    onEnterEditModeFromEdge?: (event: React.MouseEvent<HTMLDivElement>, edge: EditModeEdge) => void
    moreButtonOverlay?: MoreProps['overlay']
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
    showEditingControls?: boolean
}

function DashboardImageTileInternal(
    {
        tile,
        image,
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
    }: DashboardImageTileProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const [isImagePreviewOpen, setIsImagePreviewOpen] = React.useState(false)
    const shouldHideMoreButton = placement === DashboardPlacement.Public || showEditingControls === false
    const isTransparent = tile.transparent_background
    const imageStyle = {
        objectPosition: imageTilePositionToCss(image.position),
    }

    return (
        <>
            <div
                className={clsx(
                    'DashboardTileCard DashboardImageTile rounded flex flex-col',
                    !isTransparent && 'bg-surface-primary border',
                    isTransparent && showResizeHandles && 'border border-dashed border-border',
                    className
                )}
                data-attr="image-tile"
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
                        'DashboardTileCard__body ImageTile__body flex flex-1 min-h-0 w-full overflow-hidden p-4',
                        onDragHandleMouseDown && 'cursor-grab'
                    )}
                    onMouseDown={onDragHandleMouseDown}
                >
                    {showResizeHandles ? (
                        <div className="flex h-full w-full items-center justify-center overflow-hidden rounded">
                            <img
                                src={image.src}
                                alt={image.alt}
                                draggable={false}
                                className={clsx(
                                    'h-full w-full',
                                    image.layout === 'cover' ? 'object-cover' : 'object-contain'
                                )}
                                style={imageStyle}
                            />
                        </div>
                    ) : (
                        <button
                            type="button"
                            className="flex h-full w-full cursor-pointer items-center justify-center overflow-hidden rounded"
                            onClick={() => setIsImagePreviewOpen(true)}
                            aria-label={image.alt || 'Open image preview'}
                            data-attr="open-image-tile-preview"
                        >
                            <img
                                src={image.src}
                                alt={image.alt}
                                draggable={false}
                                className={clsx(
                                    'h-full w-full',
                                    image.layout === 'cover' ? 'object-cover' : 'object-contain'
                                )}
                                style={imageStyle}
                            />
                        </button>
                    )}
                </div>
                {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                    <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
                )}
                {showResizeHandles && <DashboardResizeHandles />}
                {children}
            </div>
            <LemonModal
                isOpen={isImagePreviewOpen}
                onClose={() => setIsImagePreviewOpen(false)}
                title="Image preview"
                width="90vw"
                maxWidth={1400}
            >
                <img src={image.src} alt={image.alt} className="h-[80vh] w-full object-contain" />
            </LemonModal>
        </>
    )
}

export const DashboardImageTile = React.forwardRef<HTMLDivElement, DashboardImageTileProps>(DashboardImageTileInternal)
