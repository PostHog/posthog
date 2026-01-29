import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'

import { EventsQuery } from '~/queries/schema/schema-general'

import { EventName as EventNameComponent } from 'products/actions/frontend/components/EventName'

interface EventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function EventsFilter({ query, setQuery }: EventsFilterProps): JSX.Element {
    const events = query.events || []
    const [isOpen, setIsOpen] = useState(false)

    const handleAddEvent = (eventName: string): void => {
        if (!events.includes(eventName)) {
            setQuery?.({ ...query, events: [...events, eventName] })
        }
        setIsOpen(false)
    }

    const handleRemoveEvent = (index: number): void => {
        const newEvents = events.filter((_, i) => i !== index)
        setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
    }

    const handleUpdateEvent = (index: number, value: string | null): void => {
        if (value) {
            const newEvents = [...events]
            newEvents[index] = value
            setQuery?.({ ...query, events: newEvents })
        } else {
            handleRemoveEvent(index)
        }
    }

    // No events selected - show single selector for first event
    if (events.length === 0) {
        return (
            <EventNameComponent
                value={null}
                disabled={!setQuery}
                onChange={(value) => value && handleAddEvent(value)}
                allEventsOption="explicit"
                placeholder="Select event"
            />
        )
    }

    // Events selected - show them with "Add event" button
    return (
        <div className="flex items-center gap-1 flex-wrap">
            {events.map((event, index) => (
                <EventNameComponent
                    key={index}
                    value={event}
                    disabled={!setQuery}
                    onChange={(value) => handleUpdateEvent(index, value)}
                    allEventsOption="clear"
                    placeholder="Select event"
                />
            ))}
            <LemonDropdown
                overlay={
                    <TaxonomicFilter
                        groupType={TaxonomicFilterGroupType.Events}
                        value={null}
                        onChange={(_, payload) => handleAddEvent(payload as string)}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    />
                }
                matchWidth={false}
                actionable
                visible={isOpen}
                onClickOutside={() => setIsOpen(false)}
            >
                <LemonButton
                    icon={<IconPlusSmall />}
                    size="small"
                    type="secondary"
                    onClick={() => setIsOpen(!isOpen)}
                    tooltip="Add another event to filter by (OR)"
                >
                    Add event
                </LemonButton>
            </LemonDropdown>
        </div>
    )
}
