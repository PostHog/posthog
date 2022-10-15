import React from 'react'
import { Resizeable } from 'lib/components/Cards/InsightCard/InsightCard'
import './TextCard.scss'
import { Textfit } from 'react-textfit'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/InsightCard/handles'
import clsx from 'clsx'
import { DashboardTile, DashboardType } from '~/types'
import { LemonButton, LemonButtonWithPopup, LemonDivider } from '@posthog/lemon-ui'
import { More } from 'lib/components/LemonButton/More'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import ReactMarkdown from 'react-markdown'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dashboardsModel } from '~/models/dashboardsModel'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    dashboardId?: string | number
    textTile: DashboardTile
    children?: JSX.Element
    removeFromDashboard?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
}

export function TextCardBody({ text }: { text: string }): JSX.Element {
    return (
        <div className="TextCard-Body p-2 w-full h-full overflow-y-auto">
            <Textfit mode={'multi'} min={14} max={100}>
                <ReactMarkdown>{text}</ReactMarkdown>
            </Textfit>
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
            className={clsx('TextCard rounded flex flex-col', className, showResizeHandles && 'border')}
            data-attr="text-card"
            {...divProps}
            ref={ref}
        >
            <div className={clsx('flex flex-row p-2', showResizeHandles ? 'border-b' : 'border rounded-t')}>
                <UserActivityIndicator
                    className={'grow'}
                    at={text.last_modified_at}
                    by={text.created_by || text.last_modified_by}
                />
                <div className="min-h-4 flex items-center justify-end">
                    <More
                        overlay={
                            <>
                                <LemonButton
                                    status="stealth"
                                    fullWidth
                                    onClick={() =>
                                        dashboardId && push(urls.dashboardTextTile(dashboardId, textTile.id))
                                    }
                                    data-attr="edit-text"
                                >
                                    Edit text
                                </LemonButton>

                                {moveToDashboard && otherDashboards.length > 0 && (
                                    <LemonButtonWithPopup
                                        status="stealth"
                                        popup={{
                                            overlay: otherDashboards.map((otherDashboard) => (
                                                <LemonButton
                                                    key={otherDashboard.id}
                                                    status="stealth"
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
                                            closeParentPopupOnClickInside: true,
                                        }}
                                        fullWidth
                                        data-attr={'text-move-to-dashboard'}
                                    >
                                        Move to
                                    </LemonButtonWithPopup>
                                )}
                                <LemonButton
                                    status="stealth"
                                    onClick={duplicate}
                                    fullWidth
                                    data-attr={'duplicate-text-from-dashboard'}
                                >
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
                                        Remove from dashboard
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                </div>
            </div>

            <TextCardBody text={text.body} />

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
