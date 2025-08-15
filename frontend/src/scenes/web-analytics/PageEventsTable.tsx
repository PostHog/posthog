import { useValues } from 'kea'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { PersonDisplay } from 'scenes/persons/PersonDisplay'
import { EventCopyLinkButton } from '~/queries/nodes/DataTable/EventRowActions'
import { pageEventsTableLogic } from './pageEventsTableLogic'

interface PageEvent {
    uuid: string
    event: string
    distinct_id: string
    timestamp: string
    properties: Record<string, any>
}

const columns: LemonTableColumns<PageEvent> = [
    {
        title: 'Event',
        key: 'event',
        className: 'max-w-80',
        render: function Render(_, event: PageEvent) {
            return <PropertyKeyInfo value={event.event} type={TaxonomicFilterGroupType.Events} />
        },
    },
    {
        title: 'Person',
        key: 'person',
        className: 'max-w-80',
        render: function Render(_, event: PageEvent) {
            return <PersonDisplay person={{ distinct_id: event.distinct_id }} />
        },
    },
    {
        title: 'Full URL',
        key: 'full_url',
        className: 'max-w-80',
        render: function Render(_, event: PageEvent) {
            const currentUrl = event.properties['$current_url']
            const screenName = event.properties['$screen_name']
            return <span className="truncate">{currentUrl || screenName}</span>
        },
    },
    {
        title: 'Query Parameters',
        key: 'query_params',
        className: 'max-w-80',
        render: function Render(_, event: PageEvent) {
            const currentUrl = event.properties['$current_url']
            if (!currentUrl) {
                return null
            }

            try {
                const url = new URL(currentUrl)
                const params = Array.from(url.searchParams.entries())
                if (params.length === 0) {
                    return <span className="text-muted">None</span>
                }

                return (
                    <div className="text-xs">
                        {params.slice(0, 3).map(([key, value], index) => (
                            <div key={index} className="truncate">
                                <span className="font-mono">{key}=</span>
                                <span>{value}</span>
                            </div>
                        ))}
                        {params.length > 3 && <div className="text-muted">+{params.length - 3} more</div>}
                    </div>
                )
            } catch {
                return <span className="text-muted">Invalid URL</span>
            }
        },
    },
    {
        title: 'Time',
        key: 'timestamp',
        className: 'max-w-80',
        render: function Render(_, event: PageEvent) {
            return <TZLabel time={event.timestamp} />
        },
    },
    {
        dataIndex: '__more' as any,
        render: function Render(_, event: PageEvent) {
            return <EventCopyLinkButton event={event} />
        },
        width: 0,
    },
]

export interface PageEventsTableProps {
    pageUrl: string
}

export function PageEventsTable({ pageUrl }: PageEventsTableProps): JSX.Element {
    const { events, eventsLoading } = useValues(pageEventsTableLogic({ pageUrl }))

    return (
        <div className="space-y-2">
            <div className="flex items-center justify-between">
                <h3 className="text-lg font-semibold">Page Activity</h3>
                <span className="text-xs text-muted">Individual events for this page grouped by query parameters</span>
            </div>

            <LemonTable
                columns={columns}
                dataSource={events}
                loading={eventsLoading}
                rowKey="uuid"
                useURLForSorting={false}
                emptyState={
                    <div className="flex flex-col justify-center items-center gap-4 p-6">
                        <span className="text-lg font-title font-semibold leading-tight">
                            No events found for this page
                        </span>
                        <span className="text-sm text-muted">
                            Events may take a few minutes to appear after they occur
                        </span>
                    </div>
                }
                nouns={['event', 'events']}
                pagination={{
                    controlled: true,
                    pageSize: 20,
                    showSizeChanger: false,
                }}
            />
        </div>
    )
}
