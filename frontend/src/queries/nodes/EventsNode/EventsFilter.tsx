import { useState } from 'react'

import { IconPlusSmall } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EventsQuery } from '~/queries/schema/schema-general'

import { EventName as EventNameComponent } from 'products/actions/frontend/components/EventName'

interface EventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function EventsFilter({ query, setQuery }: EventsFilterProps): JSX.Element {
    const events = query.events || []
    const [isAdding, setIsAdding] = useState(false)

    const handleAddEvent = (value: string | null): void => {
        if (value) {
            setQuery?.({ ...query, events: [...events, value] })
        }
        setIsAdding(false)
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
            {isAdding ? (
                <EventNameComponent
                    value={null}
                    disabled={!setQuery}
                    onChange={handleAddEvent}
                    allEventsOption="clear"
                    placeholder="Select event"
                />
            ) : (
                <LemonButton
                    icon={<IconPlusSmall />}
                    size="small"
                    type="secondary"
                    onClick={() => setIsAdding(true)}
                    tooltip="Add another event to filter by (OR)"
                >
                    Add event
                </LemonButton>
            )}
        </div>
    )
}
