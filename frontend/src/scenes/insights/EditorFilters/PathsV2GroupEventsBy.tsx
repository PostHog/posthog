import { useActions, useValues } from 'kea'
import { pathsV2DataLogic } from 'scenes/paths-v2/pathsV2DataLogic'

import { ActionFilter } from '../filters/ActionFilter/ActionFilter'
import { MathAvailability } from '../filters/ActionFilter/ActionFilterRow/ActionFilterRow'
import { keyForInsightLogicProps } from '../sharedUtils'
import { FilterType } from '~/types'
import { insightLogic } from '../insightLogic'
import { TaxonomicFilterGroupType } from '~/lib/components/TaxonomicFilter/types'
import { LemonLabel } from '@posthog/lemon-ui'
import { TaxonomicPropertyFilter } from 'lib/components/PropertyFilters/components/TaxonomicPropertyFilter'
import { useState } from 'react'

type ExpandedEvent = {
    event: any
    property: string
    path_cleaning?: boolean
}

export function PathsV2GroupEventsBy(): JSX.Element {
    const { insightProps } = useValues(insightLogic)

    const [expandedEvents, setExpandedEvents] = useState<Partial<ExpandedEvent>[]>([{}])

    const eventName = '$pageview'
    const pageKey = `${eventName}.PropertyGroupBy`

    console.debug('expandedEvents!!', !!expandedEvents[0].event)

    return (
        <div>
            {expandedEvents.map((expandedEvent, index) => (
                <div className="border rounded-md p-2">
                    <ActionFilter
                        actionsTaxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                        filters={expandedEvent.event ? { events: [expandedEvent.event] } : { events: [] }}
                        setFilters={(payload: Partial<FilterType>): void => {
                            console.debug('payload', payload)
                            setExpandedEvents((prevEvents) => {
                                const newEvents = [...prevEvents]
                                newEvents[index] = { ...prevEvents[index], event: payload.events?.[0] }
                                return newEvents
                            })
                        }}
                        typeKey={`${keyForInsightLogicProps('new')(insightProps)}-${index}`}
                        mathAvailability={MathAvailability.None}
                        entitiesLimit={!!expandedEvent.event ? 1 : undefined} // :HACKY: necessary to display the button when no event is selected
                        hideRename
                        hideDuplicate
                        hideFilter
                    />
                    {expandedEvent.event && (
                        <div className="flex items-center gap-2 mt-1">
                            <LemonLabel>By</LemonLabel>
                            <TaxonomicPropertyFilter
                                eventNames={[eventName]}
                                pageKey={pageKey}
                                index={0}
                                filters={[{ type: 'event', key: '$browser', operator: 'exact' }]}
                                onComplete={() => {
                                    // if (isValidPropertyFilter(filter) && !filter.key) {
                                    //     onRemove()
                                    // }
                                }}
                                setFilter={(_, property) => {
                                    console.debug('property', _, property)
                                    setExpandedEvents((prevEvents) => {
                                        const newEvents = [...prevEvents]
                                        newEvents[index] = { ...prevEvents[index], property: property.key }
                                        return newEvents
                                    })
                                }}
                                disablePopover={true}
                                taxonomicGroupTypes={[TaxonomicFilterGroupType.EventProperties]}
                            />
                        </div>
                    )}
                </div>
            ))}
        </div>
    )
}
