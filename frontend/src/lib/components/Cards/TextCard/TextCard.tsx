import './TextCard.scss'

import { LemonButton, LemonButtonWithDropdown, LemonDivider } from '@posthog/lemon-ui'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { Resizeable } from 'lib/components/Cards/CardMeta'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/handles'
import { More } from 'lib/lemon-ui/LemonButton/More'
import { LemonMarkdown } from 'lib/lemon-ui/LemonMarkdown'
import React from 'react'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'
import { DashboardBasicType, DashboardTile, QueryBasedInsightModel } from '~/types'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    dashboardId?: string | number
    textTile: DashboardTile<QueryBasedInsightModel>
    children?: JSX.Element
    removeFromDashboard?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardBasicType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
}

interface TextCardBodyProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'className'> {
    text: string
    closeDetails?: () => void
}

export function TextContent({ text, closeDetails, className }: TextCardBodyProps): JSX.Element {
    return (
        <div className={clsx('p-2 w-full overflow-auto', className)} onClick={() => closeDetails?.()}>
            <LemonMarkdown>{text}</LemonMarkdown>
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
        dashboardId,
        moreButtons,
        removeFromDashboard,
        duplicate,
        moveToDashboard,
        showEditingControls = true,
        ...divProps
    }: TextCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { push } = useActions(router)
    const { text } = textTile

    if (!text) {
        throw new Error('TextCard requires text')
    }

    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((dashboard) => dashboard.id !== dashboardId)
    return (
        <div
            className={clsx(
                'TextCard bg-bg-light border rounded flex flex-col',
                className,
                showResizeHandles && 'border'
            )}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            {showEditingControls && (
                <div className="absolute right-4 top-4">
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    fullWidth
                                    onClick={() =>
                                        dashboardId && push(urls.dashboardTextTile(dashboardId, textTile.id))
                                    }
                                    data-attr="edit-text"
                                >
                                    Edit text
                                </LemonButton>

                                {moveToDashboard && otherDashboards.length > 0 && (
                                    <LemonButtonWithDropdown
                                        dropdown={{
                                            overlay: otherDashboards.map((otherDashboard) => (
                                                <LemonButton
                                                    key={otherDashboard.id}
                                                    onClick={() => {
                                                        moveToDashboard(otherDashboard)
                                                    }}
                                                    fullWidth
                                                >
                                                    {otherDashboard.name || <i>Untitled</i>}
                                                </LemonButton>
                                            )),
                                            placement: 'right-start',
                                            fallbackPlacements: ['left-start'],
                                            actionable: true,
                                            closeParentPopoverOnClickInside: true,
                                        }}
                                        fullWidth
                                    >
                                        Move to
                                    </LemonButtonWithDropdown>
                                )}
                                <LemonButton onClick={duplicate} fullWidth data-attr="duplicate-text-from-dashboard">
                                    Duplicate
                                </LemonButton>
                                {moreButtons && (
                                    <>
                                        <LemonDivider />
                                        {moreButtons}
                                    </>
                                )}
                                <LemonDivider />
                                {removeFromDashboard && (
                                    <LemonButton
                                        status="danger"
                                        onClick={removeFromDashboard}
                                        fullWidth
                                        data-attr="remove-text-tile-from-dashboard"
                                    >
                                        Delete
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                </div>
            )}

            <div className="TextCard__body w-full">
                <TextContent text={text.body} className="p-4" />
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
