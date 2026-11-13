import './TextCard.scss'

import clsx from 'clsx'
import React from 'react'

import 'lib/components/Cards/CardMeta.scss'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { QuillCardMoreMenu } from 'lib/components/Cards/QuillCardMoreMenu'
import { LazyTextContent } from 'lib/components/RichContentEditor/LazyRichContent'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'

import { DashboardPlacement, DashboardTile } from '~/types'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    textTile: DashboardTile
    placement: DashboardPlacement
    children?: JSX.Element
    moreButtonOverlay?: MoreProps['overlay']
    /** Quill rows for the "more" menu, shown instead of `moreButtonOverlay`. */
    quillMenuItems?: JSX.Element
    /** Whether editing controls (three-dots menu) should be shown. False hides them on template dashboards in view mode. */
    showEditingControls?: boolean
}

function TextCardInternal(
    {
        textTile,
        showResizeHandles,
        children,
        className,
        moreButtonOverlay,
        quillMenuItems,
        placement,
        showEditingControls,
        ...divProps
    }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { text } = textTile

    if (!text) {
        throw new Error('TextCard requires text')
    }

    const shouldHideMoreButton = placement === DashboardPlacement.Public || showEditingControls === false

    const isTransparent = textTile.transparent_background
    return (
        <div
            className={clsx(
                'DashboardTileCard TextCard rounded flex flex-col',
                !isTransparent && 'bg-surface-primary border',
                isTransparent && showResizeHandles && 'border border-dashed border-border',
                className
            )}
            data-attr="text-card"
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

            <div className="DashboardTileCard__body TextCard__body w-full">
                <LazyTextContent text={text.body} className={shouldHideMoreButton ? 'p-4' : 'p-4 pr-14'} />
            </div>

            {showResizeHandles && <DashboardResizeHandles />}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const TextCard = React.forwardRef<HTMLDivElement, TextCardProps>(TextCardInternal)
