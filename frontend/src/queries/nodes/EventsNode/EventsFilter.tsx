import { useState } from 'react'

import { IconPlusSmall, IconX } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { TaxonomicFilter } from 'lib/components/TaxonomicFilter/TaxonomicFilter'
import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'
import { Popover } from 'lib/lemon-ui/Popover'

import { EventsQuery } from '~/queries/schema/schema-general'

interface EventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function EventsFilter({ query, setQuery }: EventsFilterProps): JSX.Element {
    const events = query.events || []
    const [adding, setAdding] = useState(false)

    const handleAddEvent = (value: string): void => {
        if (value && !events.includes(value)) {
            setQuery?.({ ...query, events: [...events, value] })
        }
        setAdding(false)
    }

    const handleRemoveEvent = (index: number): void => {
        const newEvents = events.filter((_, i) => i !== index)
        setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
    }

    const handleUpdateEvent = (index: number, value: string): void => {
        if (value && value !== events[index]) {
            if (events.includes(value)) {
                // Selected an already-added event, just remove the current one
                handleRemoveEvent(index)
            } else {
                const newEvents = [...events]
                newEvents[index] = value
                setQuery?.({ ...query, events: newEvents })
            }
        }
    }

    return (
        <div className="flex items-center gap-1 flex-wrap">
            {events.map((event, index) => (
                <EventChip
                    key={`${event}-${index}`}
                    event={event}
                    selectedEvents={events}
                    onUpdate={(value) => handleUpdateEvent(index, value)}
                    onRemove={() => handleRemoveEvent(index)}
                    disabled={!setQuery}
                />
            ))}
            <Popover
                visible={adding}
                onClickOutside={() => setAdding(false)}
                overlay={
                    <TaxonomicFilter
                        groupType={TaxonomicFilterGroupType.Events}
                        value={undefined}
                        onChange={(_group, value) => handleAddEvent(String(value))}
                        taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                        excludedProperties={{ [TaxonomicFilterGroupType.Events]: [null] }}
                        selectedProperties={{ [TaxonomicFilterGroupType.Events]: events }}
                    />
                }
            >
                <LemonButton
                    icon={<IconPlusSmall />}
                    size="small"
                    type="secondary"
                    onClick={() => setAdding(!adding)}
                    disabledReason={!setQuery ? 'Cannot edit filters' : undefined}
                    data-attr="events-filter-add-button"
                >
                    Select events
                </LemonButton>
            </Popover>
        </div>
    )
}

interface EventChipProps {
    event: string
    selectedEvents: string[]
    onUpdate: (value: string) => void
    onRemove: () => void
    disabled?: boolean
}

function EventChip({ event, selectedEvents, onUpdate, onRemove, disabled }: EventChipProps): JSX.Element {
    const [editing, setEditing] = useState(false)

    return (
        <Popover
            visible={editing}
            onClickOutside={() => setEditing(false)}
            overlay={
                <TaxonomicFilter
                    groupType={TaxonomicFilterGroupType.Events}
                    value={event}
                    onChange={(_group, value) => {
                        onUpdate(String(value))
                        setEditing(false)
                    }}
                    taxonomicGroupTypes={[TaxonomicFilterGroupType.Events]}
                    excludedProperties={{ [TaxonomicFilterGroupType.Events]: [null] }}
                    selectedProperties={{ [TaxonomicFilterGroupType.Events]: selectedEvents }}
                />
            }
        >
            <span className="inline-flex items-center gap-0.5 bg-accent-highlight-secondary rounded px-1.5 py-0.5 text-sm max-w-full">
                <button
                    className="inline-flex items-center gap-0.5 cursor-pointer bg-transparent border-0 p-0"
                    onClick={() => !disabled && setEditing(!editing)}
                    type="button"
                >
                    <PropertyKeyInfo value={event} disablePopover type={TaxonomicFilterGroupType.Events} ellipsis />
                </button>
                {!disabled && (
                    <LemonButton
                        size="xsmall"
                        icon={<IconX />}
                        onClick={(e) => {
                            e.stopPropagation()
                            onRemove()
                        }}
                        className="p-0.5"
                    />
                )}
            </span>
        </Popover>
    )
}
