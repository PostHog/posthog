import './TextCard.scss'

import clsx from 'clsx'
import React from 'react'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { DashboardResizeHandles } from 'lib/components/Cards/handles'
import { EditModeEdgeOverlay } from 'lib/components/Cards/InsightCard/EditModeEdgeOverlay'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    textTile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    children?: JSX.Element
    /** Whether hovering near the card edge should hint that edit mode is available. */
    canEnterEditModeFromEdge?: boolean
    /** Called when the user clicks an edge hint to enter edit mode. */
    onEnterEditModeFromEdge?: () => void
    moreButtonOverlay?: MoreProps['overlay']
    /** Called when the user mousedowns on the card body (drag handle) in view mode to enter edit mode. */
    onDragHandleMouseDown?: React.MouseEventHandler<HTMLDivElement>
}

interface TextCardBodyProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'className'> {
    text: string
    closeDetails?: () => void
}

export function TextContent({ text, closeDetails, className }: TextCardBodyProps): JSX.Element {
    return (
        <div className={clsx('w-full', className)} onClick={() => closeDetails?.()}>
            <LemonMarkdown className="overflow-auto">{text}</LemonMarkdown>
        </div>
    )
}

export function TextCardInternal(
    {
        textTile,
        showResizeHandles,
        children,
        className,
        moreButtonOverlay,
        placement,
        canEnterEditModeFromEdge,
        onEnterEditModeFromEdge,
        onDragHandleMouseDown,
        ...divProps
    }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { text } = textTile

    if (!text) {
        throw new Error('TextCard requires text')
    }

    const shouldHideMoreButton = placement === DashboardPlacement.Public

    return (
        <div
            className={clsx('TextCard bg-surface-primary border rounded flex flex-col', className)}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            {moreButtonOverlay && !shouldHideMoreButton && (
                <div className="absolute right-4 top-4">
                    <More overlay={moreButtonOverlay} />
                </div>
            )}

            <div
                className={clsx('TextCard__body w-full', onDragHandleMouseDown && 'cursor-grab')}
                onMouseDown={onDragHandleMouseDown}
            >
                <TextContent text={text.body} className="p-4 pr-14" />
            </div>

            {canEnterEditModeFromEdge && !showResizeHandles && onEnterEditModeFromEdge && (
                <EditModeEdgeOverlay onEnterEditMode={onEnterEditModeFromEdge} />
            )}
            {showResizeHandles && <DashboardResizeHandles />}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const TextCard = React.forwardRef(TextCardInternal) as typeof TextCardInternal
