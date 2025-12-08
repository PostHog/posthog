import { useRef, useState } from 'react'

import { IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { EventsQuery } from '~/queries/schema/schema-general'

import { EventName as EventNameComponent } from 'products/actions/frontend/components/EventName'

interface SecondEventNameProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function SecondEventName({ query, setQuery }: SecondEventNameProps): JSX.Element {
    const [isExpanded, setIsExpanded] = useState(!!query.secondEvent)
    const hasValue = !!query.secondEvent
    const wasExpandedByUser = useRef(false)

    const handleChange = (value: string | null): void => {
        setQuery?.({ ...query, secondEvent: value })
        if (value === null && !wasExpandedByUser.current) {
            setIsExpanded(false)
        }
    }

    const handleExpand = (): void => {
        wasExpandedByUser.current = true
        setIsExpanded(true)
    }

    const handleCollapse = (): void => {
        wasExpandedByUser.current = false
        setIsExpanded(false)
    }

    if (!isExpanded) {
        return (
            <LemonButton
                icon={<IconPlusSmall />}
                size="small"
                type="secondary"
                onClick={handleExpand}
                tooltip="Add second event filter"
            />
        )
    }

    return (
        <div className="flex items-center gap-1">
            <EventNameComponent
                value={query.secondEvent ?? null}
                disabled={!setQuery}
                onChange={handleChange}
                allEventsOption="clear"
                placeholder="Select second event"
            />
            {!hasValue && (
                <LemonButton icon={<IconX />} size="small" type="tertiary" onClick={handleCollapse} tooltip="Cancel" />
            )}
        </div>
    )
}
