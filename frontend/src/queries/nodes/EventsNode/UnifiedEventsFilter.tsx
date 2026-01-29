import { BindLogic, useActions, useValues } from 'kea'
import { useMemo, useRef, useState } from 'react'

import { IconCheck } from '@posthog/icons'
import { LemonButton, LemonDropdown, LemonInput } from '@posthog/lemon-ui'

import { ControlledDefinitionPopover } from 'lib/components/DefinitionPopover/DefinitionPopoverContents'
import { definitionPopoverLogic } from 'lib/components/DefinitionPopover/definitionPopoverLogic'
import { PropertyKeyInfo } from 'lib/components/PropertyKeyInfo'
import { infiniteListLogic } from 'lib/components/TaxonomicFilter/infiniteListLogic'
import { taxonomicFilterLogic } from 'lib/components/TaxonomicFilter/taxonomicFilterLogic'
import {
    TaxonomicDefinitionTypes,
    TaxonomicFilterGroup,
    TaxonomicFilterGroupType,
    TaxonomicFilterLogicProps,
} from 'lib/components/TaxonomicFilter/types'
import { LemonSnack } from 'lib/lemon-ui/LemonSnack/LemonSnack'
import { Spinner } from 'lib/lemon-ui/Spinner'

import { EventsQuery } from '~/queries/schema/schema-general'

import { unifiedEventsFilterLogic } from './unifiedEventsFilterLogic'

let uniqueFilterIndex = 0

interface UnifiedEventsFilterProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
    filterKey?: string
    /** If true, chips are rendered inline. If false, only the button is rendered. */
    showChipsInline?: boolean
}

export function UnifiedEventsFilter({
    query,
    setQuery,
    filterKey,
    showChipsInline = true,
}: UnifiedEventsFilterProps): JSX.Element {
    // Generate a stable key for this component instance
    const logicKey = useMemo(() => filterKey ?? `unified-events-filter-${uniqueFilterIndex++}`, [filterKey])

    const { isOpen } = useValues(unifiedEventsFilterLogic({ key: logicKey }))
    const { setIsOpen } = useActions(unifiedEventsFilterLogic({ key: logicKey }))

    const selectedEvents = query.events || []

    const handleToggleEvent = (eventName: string): void => {
        const newEvents = selectedEvents.includes(eventName)
            ? selectedEvents.filter((e) => e !== eventName)
            : [...selectedEvents, eventName]
        setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
    }

    const handleRemoveEvent = (eventName: string): void => {
        const newEvents = selectedEvents.filter((e) => e !== eventName)
        setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
    }

    const taxonomicFilterLogicProps: TaxonomicFilterLogicProps = {
        taxonomicFilterLogicKey: logicKey,
        groupType: TaxonomicFilterGroupType.Events,
        taxonomicGroupTypes: [TaxonomicFilterGroupType.Events],
        onChange: () => {},
        selectFirstItem: false,
        popoverEnabled: false,
    }

    return (
        <BindLogic logic={taxonomicFilterLogic} props={taxonomicFilterLogicProps}>
            <LemonDropdown
                visible={isOpen}
                onVisibilityChange={setIsOpen}
                closeOnClickInside={false}
                matchWidth={false}
                overlay={
                    <EventsDropdownContent
                        taxonomicFilterLogicProps={taxonomicFilterLogicProps}
                        selectedEvents={selectedEvents}
                        onToggleEvent={handleToggleEvent}
                    />
                }
            >
                <LemonButton type="secondary" size="small">
                    {selectedEvents.length === 0 ? 'Select events' : 'Add event'}
                </LemonButton>
            </LemonDropdown>
            {showChipsInline && selectedEvents.length > 0 && (
                <div className="flex items-center gap-1 flex-wrap ml-1">
                    {selectedEvents.map((eventName) => (
                        <LemonSnack key={eventName} onClose={() => handleRemoveEvent(eventName)}>
                            {eventName}
                        </LemonSnack>
                    ))}
                </div>
            )}
        </BindLogic>
    )
}

interface SelectedEventsChipsProps {
    query: EventsQuery
    setQuery?: (query: EventsQuery) => void
}

export function SelectedEventsChips({ query, setQuery }: SelectedEventsChipsProps): JSX.Element | null {
    const selectedEvents = query.events || []

    const handleRemoveEvent = (eventName: string): void => {
        const newEvents = selectedEvents.filter((e) => e !== eventName)
        setQuery?.({ ...query, events: newEvents.length > 0 ? newEvents : null })
    }

    if (selectedEvents.length === 0) {
        return null
    }

    return (
        <div className="flex items-center gap-1 flex-wrap">
            {selectedEvents.map((eventName) => (
                <LemonSnack key={eventName} onClose={() => handleRemoveEvent(eventName)}>
                    {eventName}
                </LemonSnack>
            ))}
        </div>
    )
}

interface EventsDropdownContentProps {
    taxonomicFilterLogicProps: TaxonomicFilterLogicProps
    selectedEvents: string[]
    onToggleEvent: (eventName: string) => void
}

function EventsDropdownContent({
    taxonomicFilterLogicProps,
    selectedEvents,
    onToggleEvent,
}: EventsDropdownContentProps): JSX.Element {
    const { searchQuery } = useValues(taxonomicFilterLogic)
    const { setSearchQuery } = useActions(taxonomicFilterLogic)

    const listLogicProps = {
        ...taxonomicFilterLogicProps,
        listGroupType: TaxonomicFilterGroupType.Events,
    }

    return (
        <BindLogic logic={infiniteListLogic} props={listLogicProps}>
            <div className="max-w-100 space-y-2">
                <LemonInput
                    type="search"
                    placeholder="Search events..."
                    autoFocus
                    value={searchQuery}
                    onChange={setSearchQuery}
                    fullWidth
                />
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
    const { activeTaxonomicGroup } = useValues(taxonomicFilterLogic)

    const [hoveredItem, setHoveredItem] = useState<TaxonomicDefinitionTypes | null>(null)
    const [hoveredElement, setHoveredElement] = useState<HTMLDivElement | null>(null)
    const hoverTimeoutRef = useRef<NodeJS.Timeout | null>(null)
    const isHoveringPopoverRef = useRef(false)

    // Build a map of event names to their full item objects
    const itemsByName = useMemo(() => {
        const map = new Map<string, TaxonomicDefinitionTypes>()
        for (const item of results) {
            const name = (item as { name: string }).name
            if (name) {
                map.set(name, item)
            }
        }
        return map
    }, [results])

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

    const handleMouseEnter = (eventName: string, element: HTMLDivElement): void => {
        if (hoverTimeoutRef.current) {
            clearTimeout(hoverTimeoutRef.current)
        }
        hoverTimeoutRef.current = setTimeout(() => {
            const item = itemsByName.get(eventName)
            if (item) {
                setHoveredItem(item)
                setHoveredElement(element)
            }
        }, 300)
    }

    const handleMouseLeave = (): void => {
        // Only clear the pending hover timeout, don't hide the popover
        // The popover will change when hovering a different item
        if (hoverTimeoutRef.current) {
            clearTimeout(hoverTimeoutRef.current)
            hoverTimeoutRef.current = null
        }
    }

    const handleListMouseLeave = (): void => {
        // When leaving the entire list, hide the popover after a delay
        // unless the mouse moved to the popover
        if (hoverTimeoutRef.current) {
            clearTimeout(hoverTimeoutRef.current)
        }
        hoverTimeoutRef.current = setTimeout(() => {
            if (!isHoveringPopoverRef.current) {
                setHoveredItem(null)
                setHoveredElement(null)
            }
        }, 300)
    }

    const handlePopoverMouseEnter = (): void => {
        isHoveringPopoverRef.current = true
        if (hoverTimeoutRef.current) {
            clearTimeout(hoverTimeoutRef.current)
            hoverTimeoutRef.current = null
        }
    }

    const handlePopoverMouseLeave = (): void => {
        isHoveringPopoverRef.current = false
        hoverTimeoutRef.current = setTimeout(() => {
            setHoveredItem(null)
            setHoveredElement(null)
        }, 100)
    }

    if (isLoading && sortedEvents.length === 0) {
        return (
            <div className="flex items-center justify-center p-4">
                <Spinner />
            </div>
        )
    }

    if (sortedEvents.length === 0) {
        return <div className="p-2 text-secondary italic">No events found</div>
    }

    return (
        <>
            <ul className="max-h-80 overflow-y-auto space-y-px" onMouseLeave={handleListMouseLeave}>
                {sortedEvents.map((eventName: string) => {
                    const isSelected = selectedEvents.includes(eventName)
                    return (
                        <li key={eventName}>
                            <div
                                onMouseEnter={(e) => handleMouseEnter(eventName, e.currentTarget)}
                                onMouseLeave={handleMouseLeave}
                            >
                                <LemonButton
                                    fullWidth
                                    role="menuitem"
                                    size="small"
                                    icon={isSelected ? <IconCheck className="text-success" /> : <div className="w-4" />}
                                    onClick={() => onToggleEvent(eventName)}
                                    active={isSelected}
                                >
                                    <PropertyKeyInfo
                                        value={eventName}
                                        type={TaxonomicFilterGroupType.Events}
                                        disablePopover
                                    />
                                </LemonButton>
                            </div>
                        </li>
                    )
                })}
            </ul>
            {hoveredItem && activeTaxonomicGroup && (
                <BindLogic
                    logic={definitionPopoverLogic}
                    props={{
                        type: TaxonomicFilterGroupType.Events,
                    }}
                >
                    <ControlledDefinitionPopover
                        visible={!!hoveredItem}
                        item={hoveredItem}
                        group={activeTaxonomicGroup as TaxonomicFilterGroup}
                        highlightedItemElement={hoveredElement}
                        onMouseEnterInside={handlePopoverMouseEnter}
                        onMouseLeaveInside={handlePopoverMouseLeave}
                    />
                </BindLogic>
            )}
        </>
    )
}
