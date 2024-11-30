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
        markExpanded: (id: string | null | undefined) => ({ id }),
        setHideRecordingSnapshots: (hide: boolean) => ({ hide }),
        setSearchText: (searchText: string) => ({ searchText }),
        setSearchVisible: (visible: boolean) => ({ visible }),
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
            null as string | null | undefined,
            {
                markExpanded: (_, { id }) => id,
            },
        ],
        hideRecordingSnapshots: [
            true,
            {
                setHideRecordingSnapshots: (_, { hide }) => hide,
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
            (s) => [s.hideRecordingSnapshots, s.events, s.searchText, s.isCollapsedEventRow],
            (hideRecordingSnapshots, events, searchText, isCollapsedEventRow) => {
                return events
                    .filter((e) => {
                        if (e.event !== '$snapshot') {
                            return true
                        }
                        return !hideRecordingSnapshots
                    })
                    .filter((e) => {
                        if (isCollapsedEventRow(e.uuid)) {
                            return e.event.includes(searchText)
                        }
                        // the current expanded row is always included
                        return true
                    })
            },
        ],
        filteredProperties: [
            (s) => [s.searchText],
            (searchText) => {
                return (p: Record<string, any>): Record<string, any> => {
                    // return a new object with only the properties where key or value match the search text
                    if (searchText.trim() !== '') {
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
