import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'

export type ActivityEventsWidgetEvent = {
    uuid: string
    event: string
    person: { display_name?: string; id?: string; distinct_id?: string } | null
    url: string | null
    timestamp: string
}

export function ActivityEventsWidgetRowSkeleton(): JSX.Element {
    return (
        <div className="flex items-center justify-between gap-2 border-b px-3 py-2">
            <div className="flex min-w-0 flex-1 flex-col gap-1">
                <LemonSkeleton className="h-4 w-40" />
                <LemonSkeleton className="h-3 w-64" />
            </div>
            <LemonSkeleton className="h-4 w-24 shrink-0" />
        </div>
    )
}

export function ActivityEventsWidgetRow({ event }: { event: ActivityEventsWidgetEvent }): JSX.Element {
    return (
        <div
            className="flex items-center justify-between gap-2 border-b px-3 py-2"
            data-attr="activity-events-widget-row"
        >
            <div className="flex min-w-0 flex-1 flex-col">
                <div className="flex min-w-0 items-center gap-2">
                    <span className="min-w-0 truncate text-sm font-medium">
                        <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} disablePopover />
                    </span>
                </div>
                {event.url ? <span className="min-w-0 truncate text-xs text-muted">{event.url}</span> : null}
            </div>
            <div className="flex shrink-0 items-center gap-2 text-xs">
                {event.person ? (
                    <PersonDisplay
                        person={{
                            id: event.person.id,
                            distinct_id: event.person.distinct_id,
                            properties: {},
                        }}
                        displayName={event.person.display_name}
                        withIcon
                        noPopover
                    />
                ) : null}
                <span className="whitespace-nowrap text-muted">
                    <TZLabel time={event.timestamp} />
                </span>
            </div>
        </div>
    )
}
