import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { CORE_FILTER_DEFINITIONS_BY_GROUP } from 'lib/taxonomy'
import { uuid } from 'lib/utils'
import { permanentlyMount } from 'lib/utils/kea-logic-builders'

import { toolbarConfigLogic } from '~/toolbar/toolbarConfigLogic'
import { EventType } from '~/types'

import type { eventDebugMenuLogicType } from './eventDebugMenuLogicType'

export const eventDebugMenuLogic = kea<eventDebugMenuLogicType>([
    path(['toolbar', 'debug', 'eventDebugMenuLogic']),
    connect(() => ({
        values: [toolbarConfigLogic, ['posthog']],
    })),
    actions({
        addEvent: (event: EventType) => ({ event }),
        markExpanded: (id: string | null | undefined) => ({ id }),
        setSearchText: (searchText: string) => ({ searchText }),
        setSearchVisible: (visible: boolean) => ({ visible }),
        setSelectedEventType: (eventType: 'posthog' | 'custom' | 'snapshot', enabled: boolean) => ({
            eventType,
            enabled,
        }),
    }),
    reducers({
        searchVisible: [
            false,
            {
                setSearchVisible: (_, { visible }) => visible,
            },
        ],
        searchText: [
            '',
            {
                setSearchText: (_, { searchText }) => searchText,
                // reset search on toggle
                setSearchVisible: () => '',
            },
        ],
        selectedEventTypes: [
            ['posthog', 'custom'] as ('posthog' | 'custom' | 'snapshot')[],
            {
                setSelectedEventType: (state, { eventType, enabled }) => {
                    const newTypes = [...state]
                    if (enabled) {
                        newTypes.push(eventType)
                    } else {
                        newTypes.splice(newTypes.indexOf(eventType), 1)
                    }
                    return newTypes
                },
            },
        ],

        events: [
            [] as EventType[],
            {
                addEvent: (state, { event }) => {
                    return [{ ...event, uuid: event.uuid || uuid() }, ...state]
                },
            },
        ],
        expandedEvent: [
            null as string | null | undefined,
            {
                markExpanded: (_, { id }) => id,
            },
        ],
    }),
    selectors({
        isCollapsedEventRow: [
            (s) => [s.expandedEvent],
            (expandedEvent) => {
                return (eventId: string | null | undefined): boolean => {
                    return eventId !== expandedEvent
                }
            },
        ],
        searchFilteredEvents: [
            (s) => [s.events, s.searchText],
            (events, searchText) => {
                return events.filter((e) => e.event.includes(searchText))
            },
        ],
        searchFilteredEventsCount: [
            (s) => [s.searchFilteredEvents],
            (searchFilteredEvents): { posthog: number; custom: number; snapshot: number } => {
                const counts = { posthog: 0, custom: 0, snapshot: 0 }

                searchFilteredEvents.forEach((e) => {
                    if (e.event === '$snapshot') {
                        counts.snapshot += 1
                    } else if (
                        e.event.startsWith('$') ||
                        Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.events).includes(e.event)
                    ) {
                        counts.posthog += 1
                    } else {
                        counts.custom += 1
                    }
                })

                return counts
            },
        ],

        activeFilteredEvents: [
            (s) => [s.selectedEventTypes, s.searchFilteredEvents, s.searchText, s.isCollapsedEventRow],
            (selectedEventTypes, searchFilteredEvents) => {
                return searchFilteredEvents.filter((e) => {
                    if (e.event === '$snapshot') {
                        return selectedEventTypes.includes('snapshot')
                    }
                    if (
                        e.event.startsWith('$') ||
                        Object.keys(CORE_FILTER_DEFINITIONS_BY_GROUP.events).includes(e.event)
                    ) {
                        return selectedEventTypes.includes('posthog')
                    }

                    return !!selectedEventTypes.includes('custom')
                })
            },
        ],
    }),
    afterMount(({ values, actions }) => {
        values.posthog?.on('eventCaptured', (e) => {
            actions.addEvent(e)
        })
    }),
    permanentlyMount(),
])
