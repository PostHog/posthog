import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { Link } from 'lib/lemon-ui/Link'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { urls } from 'scenes/urls'

export type ActivityEventsWidgetEvent = {
    uuid: string
    event: string
    person: { display_name?: string; id?: string; distinct_id?: string } | null
    url: string | null
    lib: string | null
    timestamp: string
}

export function ActivityEventsWidgetRowSkeleton(): JSX.Element {
    return (
        <div className="flex flex-col gap-1 px-3 py-2">
            <div className="flex items-center justify-between gap-2">
                <LemonSkeleton className="h-4 w-40" />
                <LemonSkeleton className="h-4 w-24 shrink-0" />
            </div>
            <LemonSkeleton className="h-3 w-56" />
        </div>
    )
}

export function ActivityEventsWidgetRow({ event }: { event: ActivityEventsWidgetEvent }): JSX.Element {
    return (
        <Link
            to={urls.event(event.uuid, event.timestamp)}
            target="_blank"
            subtle
            className="flex flex-col gap-0.5 px-3 py-2 hover:bg-surface-secondary"
            data-attr="activity-events-widget-row"
        >
            <div className="flex items-center justify-between gap-2">
                <span className="min-w-0 truncate text-sm font-medium">
                    <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} disablePopover />
                </span>
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
                            noLink
                            noPopover
                        />
                    ) : null}
                    <span className="whitespace-nowrap text-muted">
                        <TZLabel time={event.timestamp} />
                    </span>
                </div>
            </div>
            <div className="flex min-h-4 min-w-0 items-center gap-2 text-xs text-muted">
                {event.lib ? <span className="shrink-0">{event.lib}</span> : null}
                {event.url ? <span className="min-w-0 truncate">{event.url}</span> : null}
            </div>
        </Link>
    )
}
