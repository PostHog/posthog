import { actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
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
        markExpanded: (id: string | null) => ({ id }),
        setShowRecordingSnapshots: (show: boolean) => ({ show }),
        setSearchText: (searchText: string) => ({ searchText }),
        setSearchType: (searchType: 'events' | 'properties') => ({ searchType }),
    }),
    reducers({
        searchType: [
            'events' as 'events' | 'properties',
            {
                setSearchType: (_, { searchType }) => searchType,
            },
        ],
        searchText: [
            '',
            {
                setSearchText: (_, { searchText }) => searchText,
            },
        ],
        events: [
            [] as EventType[],
            {
                addEvent: (state, { event }) => {
                    if (!event.uuid) {
                        event.uuid = uuid()
                    }
                    return [event, ...state]
                },
            },
        ],
        expandedEvent: [
            null as string | null,
            {
                markExpanded: (_, { id }) => id,
            },
        ],
        showRecordingSnapshots: [
            false,
            {
                setShowRecordingSnapshots: (_, { show }) => show,
            },
        ],
    }),
    selectors({
        isCollapsedEventRow: [
            (s) => [s.expandedEvent],
            (expandedEvent) => {
                return (eventId: string | null): boolean => {
                    return eventId !== expandedEvent
                }
            },
        ],
        snapshotCount: [(s) => [s.events], (events) => events.filter((e) => e.event === '$snapshot').length],
        eventCount: [(s) => [s.events], (events) => events.filter((e) => e.event !== '$snapshot').length],
        filteredEvents: [
            (s) => [s.showRecordingSnapshots, s.events, s.searchText, s.searchType],
            (showRecordingSnapshots, events, searchText, searchType) => {
                return events
                    .filter((e) => {
                        if (showRecordingSnapshots) {
                            return true
                        }
                        return e.event !== '$snapshot'
                    })
                    .filter((e) => {
                        if (searchType === 'events') {
                            return e.event.includes(searchText)
                        }
                        return true
                    })
            },
        ],
        filteredProperties: [
            (s) => [s.searchText, s.searchType],
            (searchText, searchType) => {
                return (p: Record<string, any>): Record<string, any> => {
                    // return a new object with only the properties where key or value match the search text
                    if (searchType === 'properties') {
                        return Object.fromEntries(
                            Object.entries(p).filter(([key, value]) => {
                                return key.includes(searchText) || (value && value.toString().includes(searchText))
                            })
                        )
                    }
                    return p
                }
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
