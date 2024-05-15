import { LemonButton, LemonMenu, LemonSwitch } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PropertyFilters } from 'lib/components/PropertyFilters/PropertyFilters'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { TZLabel } from 'lib/components/TZLabel'
import { LemonTable, LemonTableColumns } from 'lib/lemon-ui/LemonTable'
import { liveEventsTableLogic } from 'scenes/events-management/live-events/liveEventsTableLogic'

import { EventPropertyFilter, PersonPropertyFilter, PropertyFilterType, PropertyOperator } from '~/types'

interface LiveEvent {
    uuid: string
    event: string
    properties: Record<string, any>
    timestamp: string
    team_id: number
    distinct_id: string
    elements_chain: string
    created_at: string
}

const columns: LemonTableColumns<LiveEvent> = [
    {
        title: 'ID',
        key: 'id',
        render: function Render(_, event: LiveEvent) {
            return <span className="">{event.uuid}</span>
        },
    },
    {
        title: 'Event',
        key: 'event',
        render: function Render(_, event: LiveEvent) {
            return <span className="">{event.event}</span>
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
    const { events, liveEventsLoading, filters, streamPaused, curEventProperties } = useValues(liveEventsTableLogic)
    const { setFilters, pauseStream, resumeStream, setCurEventProperties } = useActions(liveEventsTableLogic)

    const menuOptions = [
        {
            label: 'Event Type',
            key: '$event_type',
            queryKey: 'eventType',
            onClick: () => {
                const newFilter: EventPropertyFilter = {
                    key: '$event_type',
                    type: PropertyFilterType.Event,
                    operator: PropertyOperator.Exact,
                }
                setCurEventProperties([...curEventProperties, newFilter])
            },
        },
        {
            label: 'Distinct ID',
            key: 'distinct_id',
            queryKey: 'distinctId',
            onClick: () => {
                const newFilter: PersonPropertyFilter = {
                    key: 'distinct_id',
                    type: PropertyFilterType.Person,
                    operator: PropertyOperator.Exact,
                }
                setCurEventProperties([...curEventProperties, newFilter])
            },
        },
    ]

    const filteredMenuOptions = menuOptions.filter((option) => {
        return !curEventProperties.some((filter: any) => filter.key === option.key)
    })

    return (
        <div data-attr="manage-events-table">
            <div className="mb-2 flex w-full justify-between items-start">
                <div className="space-y-2 flex-1">
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
                </div>
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
                columns={columns}
                data-attr="live-events-table"
                loading={liveEventsLoading}
                rowKey="uuid"
                dataSource={events}
                useURLForSorting={false}
                emptyState="No live events"
                nouns={['event', 'events']}
            />
        </div>
    )
}
