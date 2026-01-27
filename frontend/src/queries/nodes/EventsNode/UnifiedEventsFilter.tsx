import { BindLogic, useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconCheck, IconChevronDown } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { EventsQuery } from '~/queries/schema/schema-general'

interface UnifiedEventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

let uniqueFilterIndex = 0

export function UnifiedEventsFilter({ query, setQuery }: UnifiedEventsFilterProps): JSX.Element {
    const [isOpen, setIsOpen] = useState(false)
    const [filterKey] = useState(() => `unified-events-filter-${uniqueFilterIndex++}`)

    const selectedEvents = query.events || []

    const handleToggleEvent = (eventName: string): void => {
        const newEvents = selectedEvents.includes(eventName)
            ? selectedEvents.filter((e) => e !== eventName)
            : [...selectedEvents, eventName]
        setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
    }

    const displayText = useMemo(() => {
        if (selectedEvents.length === 0) {
            return 'Select events'
        }
        if (selectedEvents.length <= 3) {
            return selectedEvents.join(', ')
        }
        return `${selectedEvents.slice(0, 2).join(', ')} +${selectedEvents.length - 2} more`
    }, [selectedEvents])

    return (
        <LemonDropdown
            visible={isOpen}
            onVisibilityChange={setIsOpen}
            closeOnClickInside={false}
            matchWidth={false}
            overlay={
                <div className="w-[400px] max-h-[500px] overflow-hidden flex flex-col">
                    <EventsSearchSection
                        filterKey={filterKey}
                        selectedEvents={selectedEvents}
                        onToggleEvent={handleToggleEvent}
                    />
                </div>
            }
        >
            <LemonButton type="secondary" size="small" sideIcon={<IconChevronDown />}>
                <span className={selectedEvents.length === 0 ? 'text-secondary' : ''}>{displayText}</span>
            </LemonButton>
        </LemonDropdown>
    )
}

interface EventsSearchSectionProps {
    filterKey: string
    selectedEvents: string[]
    onToggleEvent: (eventName: string) => void
}

function EventsSearchSection({ filterKey, selectedEvents, onToggleEvent }: EventsSearchSectionProps): JSX.Element {
    const searchInputRef = useRef<HTMLInputElement>(null)

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: filterKey,
        groupType: TaxonomicFilterGroupType.Events,
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
        onChange: () => {},
        selectFirstItem: false,
        popoverEnabled: false,
    }

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <EventsSearchContent
                searchInputRef={searchInputRef}
                taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                selectedEvents={selectedEvents}
                onToggleEvent={onToggleEvent}
            />
        </BindLogic>
    )
}

interface EventsSearchContentProps {
    searchInputRef: React.RefObject<HTMLInputElement>
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    selectedEvents: string[]
    onToggleEvent: (eventName: string) => void
}

function EventsSearchContent({
    searchInputRef,
    taxonomicFilterLogicProps,
    selectedEvents,
    onToggleEvent,
}: EventsSearchContentProps): JSX.Element {
    const { searchQuery } = useValues(taxonomicFilterLogic)
    const { setSearchQuery } = useActions(taxonomicFilterLogic)

    const listLogicProps = {
        ...taxonomicFilterLogicProps,
        listGroupType: TaxonomicFilterGroupType.Events,
    }

    return (
        <BindLogic logic={infiniteListLogic} props={listLogicProps}>
            <div className="flex flex-col flex-1 min-h-0">
                <div className="p-2 border-b border-border">
                    <LemonInput
                        ref={searchInputRef}
                        type="search"
                        placeholder="Search events..."
                        value={searchQuery}
                        onChange={setSearchQuery}
                        fullWidth
                        size="small"
                        autoFocus
                    />
                </div>
                <EventsList selectedEvents={selectedEvents} onToggleEvent={onToggleEvent} searchQuery={searchQuery} />
            </div>
        </BindLogic>
    )
}

interface EventsListProps {
    selectedEvents: string[]
    onToggleEvent: (eventName: string) => void
    searchQuery: string
}

function EventsList({ selectedEvents, onToggleEvent, searchQuery }: EventsListProps): JSX.Element {
    const { results, isLoading } = useValues(infiniteListLogic)

    const sortedEvents = useMemo(() => {
        // Filter out "All events" since default behavior already shows all events
        const apiEventNames = results
            .map((item: TaxonomicDefinitionTypes) => (item as { name: string }).name)
            .filter((name: string) => name && name.toLowerCase() !== 'all events')
        const searchLower = searchQuery.toLowerCase()

        // Filter selected events by search query
        const filteredSelected = searchQuery
            ? selectedEvents.filter((e) => e.toLowerCase().includes(searchLower))
            : selectedEvents

        // Get unselected events from API results (already filtered by search via API)
        const unselectedFromApi = apiEventNames.filter((name: string) => !selectedEvents.includes(name))

        // Combine: selected first, then unselected
        return [...filteredSelected, ...unselectedFromApi]
    }, [results, selectedEvents, searchQuery])

    if (isLoading && sortedEvents.length === 0) {
        return (
            <div className="flex items-center justify-center h-[200px]">
                <Spinner />
            </div>
        )
    }

    if (sortedEvents.length === 0) {
        return <div className="flex items-center justify-center h-[200px] text-secondary text-sm">No events found</div>
    }

    return (
        <div className="flex-1 min-h-[200px] max-h-[350px] overflow-y-auto">
            {sortedEvents.map((eventName: string) => {
                const isSelected = selectedEvents.includes(eventName)
                return (
                    <div
                        key={eventName}
                        className="flex items-center gap-2 px-3 py-2 cursor-pointer hover:bg-fill-tertiary-highlight"
                        onClick={() => onToggleEvent(eventName)}
                    >
                        <div className="w-4 h-4 flex items-center justify-center">
                            {isSelected && <IconCheck className="text-success w-4 h-4" />}
                        </div>
                        <span className={isSelected ? 'font-medium' : ''}>
                            <PropertyKeyInfo value={eventName} type={TaxonomicFilterGroupType.Events} />
                        </span>
                    </div>
                )
            })}
        </div>
    )
}
