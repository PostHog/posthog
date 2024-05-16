import { LemonBanner, LemonSwitch, Link } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { supportLogic } from 'lib/components/Support/supportLogic'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { liveEventsTableLogic } from 'scenes/events-management/live-events/liveEventsTableLogic'

interface LiveEvent {
    uuid: string
    event: string
    properties: Record<string, any>
    timestamp: string
    team_id: number
    distinct_id: string
    created_at: string
}

const columns: LemonTableColumns<LiveEvent> = [
    {
        title: 'ID',
        key: 'uuid',
        render: function Render(_, event: LiveEvent) {
            return <span>{event.uuid}</span>
        },
    },
    {
        title: 'Event',
        key: 'event',
        render: function Render(_, event: LiveEvent) {
            return <span>{event.event}</span>
        },
    },
    {
        title: 'Timestamp',
        key: 'timestamp',
        render: function Render(_, event: LiveEvent) {
            return <TZLabel time={event.timestamp} />
        },
    },
]

export function LiveEventsTable(): JSX.Element {
    const { events, stats, streamPaused } = useValues(liveEventsTableLogic)
    const { pauseStream, resumeStream } = useActions(liveEventsTableLogic)
    const { openSupportForm } = useActions(supportLogic)

    // const menuOptions = [
    //     {
    //         label: 'Event Type',
    //         key: '$event_type',
    //         queryKey: 'eventType',
    //         onClick: () => {
    //             const newFilter: EventPropertyFilter = {
    //                 key: '$event_type',
    //                 type: PropertyFilterType.Event,
    //                 operator: PropertyOperator.Exact,
    //             }
    //             setCurEventProperties([...curEventProperties, newFilter])
    //         },
    //     },
    // ]

    // const filteredMenuOptions = menuOptions.filter((option) => {
    //     return !curEventProperties.some((filter: any) => filter.key === option.key)
    // })

    return (
        <div data-attr="manage-events-table">
            <LemonBanner className="mb-4" type="info">
                Live events is a beta feature and may not be fully accurate.{' '}
                <Link onClick={() => openSupportForm({ kind: 'feedback' })}>Contact us</Link> if you need help with this
                feature.
            </LemonBanner>
            <div className="mb-2 flex w-full justify-between items-center">
                {stats?.users_on_product ? (
                    <div className="flex justify-center">
                        <div className="flex flex-justify-center items-center bg-white px-2 py-1 rounded border border-3000 text-xs font-medium text-gray-600">
                            <p className="mb-0">🚀 Live users on product: 🟢 {stats?.users_on_product}</p>
                        </div>
                    </div>
                ) : (
                    <div />
                )}
                {/* <div className="space-y-2 flex-1">
                    {filteredMenuOptions.length > 0 && (
                        <LemonMenu items={[{ items: filteredMenuOptions }]}>
                            <LemonButton size="small" type="secondary">
                                Choose filter
                            </LemonButton>
                        </LemonMenu>
                    )}

                    <PropertyFilters
                        pageKey="live-events-$event_type"
                        taxonomicGroupTypes={[
                            TaxonomicFilterGroupType.EventProperties,
                            TaxonomicFilterGroupType.PersonProperties,
                        ]}
                        propertyFilters={curEventProperties}
                        onChange={(properties) => {
                            const tempFilters = { ...filters }
                            properties.forEach((property) => {
                                const value = Array.isArray(property.value) ? property.value.join(',') : property.value
                                const queryKey = menuOptions.find((option) => option.key === property.key)?.queryKey
                                if (queryKey) {
                                    tempFilters[queryKey] = value
                                }
                            })
                            setFilters(tempFilters)
                            setCurEventProperties(properties)
                        }}
                        allowNew={false}
                        openOnInsert
                        disablePopover
                    />
                </div> */}
                <div>
                    <LemonSwitch
                        bordered
                        data-attr="live-events-refresh-toggle"
                        id="live-events-switch"
                        label={streamPaused ? 'Resume' : 'Pause'}
                        checked={streamPaused}
                        onChange={streamPaused ? resumeStream : pauseStream}
                    />
                </div>
            </div>
            <LemonTable
                // @ts-expect-error
                columns={columns}
                data-attr="live-events-table"
                rowKey="uuid"
                dataSource={events}
                useURLForSorting={false}
                emptyState="No live events"
                nouns={['event', 'events']}
            />
        </div>
    )
}
