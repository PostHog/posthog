import { Resizeable } from 'lib/components/Cards/InsightCard/InsightCard'
import './LiveEventsCard.scss'
import { ResizeHandle1D, ResizeHandle2D } from 'lib/components/Cards/InsightCard/handles'
import clsx from 'clsx'
import { DashboardTile, DashboardType } from '~/types'
import { LemonButton, LemonButtonWithPopup, LemonDivider } from '@posthog/lemon-ui'
import { More } from 'lib/components/LemonButton/More'
import { useValues } from 'kea'
import { UserActivityIndicator } from 'lib/components/UserActivityIndicator/UserActivityIndicator'
import { dashboardsModel } from '~/models/dashboardsModel'
import React from 'react'
import { EventsTable } from 'scenes/events'

interface LiveEventsCardProps extends React.HTMLAttributes<HTMLDivElement>, Resizeable {
    dashboardId?: string | number
    savedFilterTile: DashboardTile
    children?: JSX.Element
    removeFromDashboard?: () => void
    duplicate?: () => void
    moveToDashboard?: (dashboard: DashboardType) => void
    /** buttons to add to the "more" menu on the card**/
    moreButtons?: JSX.Element | null
}

export function LiveEventsCardBody({ filters }: { filters: Record<string, any> }): JSX.Element {
    return (
        <div className="LiveEventsCard-Body p-2 w-full h-full overflow-y-auto">
            <EventsTable
                pageKey={'dashboard_tile'}
                fixedFilters={filters}
                showCustomizeColumns={false}
                showExport={false}
                showAutoload={false}
                showEventFilter={false}
                showPropertyFilter={false}
                showRowExpanders={false}
                showActionsButton={false}
                showPersonColumn={true}
                linkPropertiesToFilters={false}
                data-attr={'live-events-card'}
            />
        </div>
    )
}

export function LiveEventsCardInternal(
    {
        savedFilterTile,
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
    }: LiveEventsCardProps,
    ref: React.Ref<HTMLDivElement>
): JSX.Element {
    const { saved_filter } = savedFilterTile
    if (!saved_filter) {
        throw new Error('LiveEventsCard requires saved_filter')
    }

    const { nameSortedDashboards } = useValues(dashboardsModel)
    const otherDashboards = nameSortedDashboards.filter((dashboard) => dashboard.id !== dashboardId)
    return (
        <div
            className={clsx('LiveEventsCard rounded flex flex-col border', className)}
            data-attr="live-events-card"
            {...divProps}
            ref={ref}
        >
            <div className={clsx('flex flex-row p-2')}>
                <UserActivityIndicator
                    className={'grow'}
                    at={saved_filter.last_modified_at}
                    by={saved_filter.created_by || saved_filter.last_modified_by}
                />
                <div className="min-h-4 flex items-center justify-end">
                    <More
                        overlay={
                            <>
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
                                    >
                                        Move to
                                    </LemonButtonWithPopup>
                                )}
                                <LemonButton
                                    status="stealth"
                                    onClick={duplicate}
                                    fullWidth
                                    data-attr={'duplicate-live-events-tile-from-dashboard'}
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
                                        data-attr="remove-live-events-tile-from-dashboard"
                                    >
                                        Remove from dashboard
                                    </LemonButton>
                                )}
                            </>
                        }
                    />
                </div>
            </div>

            <LiveEventsCardBody filters={saved_filter.filters} />

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

export const LiveEventsCard = React.forwardRef(LiveEventsCardInternal) as typeof LiveEventsCardInternal
