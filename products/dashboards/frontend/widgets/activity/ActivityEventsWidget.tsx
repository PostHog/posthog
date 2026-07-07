import { HedgehogMagnifyingGlass } from '@posthog/brand/hoggies'

import {
    WIDGET_LIST_COUNT_EVENTS,
    WidgetCardBodyMessage,
    WidgetCardContent,
    WidgetContentFooter,
    WidgetListCount,
} from '../../components/WidgetCard'
import type { DashboardWidgetComponentProps } from '../registry'
import {
    ActivityEventsWidgetRow,
    ActivityEventsWidgetRowSkeleton,
    type ActivityEventsWidgetEvent,
} from './ActivityEventsWidgetRow'

export type ActivityEventsWidgetResult = {
    results?: ActivityEventsWidgetEvent[]
    hasMore?: boolean
    limit?: number
    totalCount?: number
    totalCountCapped?: boolean
}

export function ActivityEventsWidget({ result, loading }: DashboardWidgetComponentProps): JSX.Element {
    const payload = result as ActivityEventsWidgetResult | null | undefined
    const events = payload?.results ?? []

    if (loading) {
        return (
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {Array.from({ length: 5 }, (_, index) => (
                        <ActivityEventsWidgetRowSkeleton key={index} />
                    ))}
                </div>
            </WidgetCardContent>
        )
    }

    if (events.length === 0) {
        return (
            <WidgetCardContent>
                <WidgetCardBodyMessage>
                    <div
                        className="flex max-w-xs flex-col items-center gap-2 px-2 text-balance"
                        data-attr="activity-events-widget-empty-state"
                    >
                        <HedgehogMagnifyingGlass className="size-20 shrink-0" />
                        <p className="m-0 text-base font-semibold text-primary">No events yet</p>
                        <p className="m-0 text-sm text-muted">No events matched your filters for this date range.</p>
                    </div>
                </WidgetCardBodyMessage>
            </WidgetCardContent>
        )
    }

    return (
        <>
            <WidgetCardContent>
                <div className="flex flex-col divide-y divide-border">
                    {events.map((event) => (
                        <ActivityEventsWidgetRow key={event.uuid} event={event} />
                    ))}
                </div>
            </WidgetCardContent>
            <WidgetContentFooter>
                <WidgetListCount
                    shown={events.length}
                    totalCount={payload?.totalCount}
                    totalCountIsLowerBound={payload?.totalCountCapped}
                    noun={WIDGET_LIST_COUNT_EVENTS}
                    hasMore={payload?.hasMore}
                    dataAttr="activity-events-widget-count"
                />
            </WidgetContentFooter>
        </>
    )
}
