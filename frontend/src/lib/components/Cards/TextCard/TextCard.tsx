import './TextCard.scss'

import clsx from 'clsx'
import React from 'react'

import { Resizeable } from 'lib/components/Cards/CardMeta'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/handles'
import { More, MoreProps } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'

import { DashboardPlacement, DashboardTile, QueryBasedInsightModel } from '~/types'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    textTile: DashboardTile<QueryBasedInsightModel>
    placement: DashboardPlacement
    children?: JSX.Element
    moreButtonOverlay?: MoreProps['overlay']
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
        canResizeWidth,
        children,
        className,
        moreButtonOverlay,
        placement,
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
            className={clsx(
                'TextCard bg-surface-primary border rounded flex flex-col',
                className,
                showResizeHandles && 'border'
            )}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            {moreButtonOverlay && !shouldHideMoreButton && (
                <div className="absolute right-4 top-4">
                    <More overlay={moreButtonOverlay} />
                </div>
            )}

            <div className="TextCard__body w-full">
                <TextContent text={text.body} className="p-4 pr-14" />
            </div>

            {showResizeHandles && (
                <>
                    {canResizeWidth ? <ResizeHandle1D orientation="vertical" /> : null}
                    <ResizeHandle1D orientation="horizontal" />
                    {canResizeWidth ? <ResizeHandle2D /> : null}
                </>
            )}
            {children /* Extras, such as resize handles */}
        </div>
    )
}

export const TextCard = React.forwardRef(TextCardInternal) as typeof TextCardInternal
