import './TextCard.scss'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/handles'
import clsx from 'clsx'
import { DashboardTile, DashboardType } from '~/types'
import { LemonButton, LemonButtonWithDropdown, LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { router } from 'kea-router'
import { urls } from 'scenes/urls'
import ReactMarkdown from 'react-markdown'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dashboardsModel } from '~/models/dashboardsModel'
import React, { useState } from 'react'
import { CardMeta, Resizeable } from 'lib/components/Cards/Card'

interface TextCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    dashboardId?: string | number
    textTile: DashboardTile
    children?: JSX.Element
    removeFromDashboard?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
    /** Whether the editing controls should be enabled or not. */
    showEditingControls?: boolean
}

interface TextCardBodyProps extends Pick<React.HTMLAttributes<HTMLDivElement>, 'style'> {
    text: string
    closeDetails?: () => void
}

export function TextContent({ text, closeDetails, style }: TextCardBodyProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="p-2 w-full overflow-auto" onClick={() => closeDetails?.()} style={style}>
            <ReactMarkdown>{text}</ReactMarkdown>
        </div>
    )
}

export function TextCardBody({ text, closeDetails, style }: TextCardBodyProps): JSX.Element {
    return (
        // eslint-disable-next-line react/forbid-dom-props
        <div className="TextCard-Body w-full" onClick={() => closeDetails?.()} style={style}>
            <TextContent text={text} />
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

    const [metaPrimaryHeight, setMetaPrimaryHeight] = useState<number | undefined>(undefined)
    const [areDetailsShown, setAreDetailsShown] = useState(false)

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
            <CardMeta
                showEditingControls={showEditingControls}
                showDetailsControls={true}
                setAreDetailsShown={setAreDetailsShown}
                areDetailsShown={areDetailsShown}
                className={clsx(showResizeHandles ? 'border-b' : 'border rounded-t')}
                metaDetails={
                    <UserActivityIndicator
                        className={'mt-1'}
                        at={text.last_modified_at}
                        by={text.created_by || text.last_modified_by}
                    />
                }
                moreButtons={
                    <>
                        <LemonButton
                            status="stealth"
                            fullWidth
                            onClick={() => dashboardId && push(urls.dashboardTextTile(dashboardId, textTile.id))}
                            data-attr="edit-text"
                        >
                            Edit text
                        </LemonButton>

                        {moveToDashboard && otherDashboards.length > 0 && (
                            <LemonButtonWithDropdown
                                status="stealth"
                                dropdown={{
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
                                    closeParentPopoverOnClickInside: true,
                                }}
                                fullWidth
                            >
                                Move to
                            </LemonButtonWithDropdown>
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
                setPrimaryHeight={setMetaPrimaryHeight}
            />

            <TextCardBody
                text={text.body}
                closeDetails={() => setAreDetailsShown(false)}
                style={
                    metaPrimaryHeight
                        ? { height: `calc(100% - ${metaPrimaryHeight}px - 2rem /* margins */ - 1px /* border */)` }
                        : undefined
                }
            />

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
