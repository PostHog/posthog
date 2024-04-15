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
    }),
    reducers({
        events: [
            [] as EventType[],
            {
                addEvent: (state, { event }) => {
                    if (event.uuid) {
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
        snapshotCount: [(s) => [s.events], (events) => events.filter((e) => e.event !== '$snapshot').length],
        eventCount: [(s) => [s.events], (events) => events.filter((e) => e.event === '$snapshot').length],
        filteredEvents: [
            (s) => [s.showRecordingSnapshots, s.events],
            (showRecordingSnapshots, events) => {
                return events.filter((e) => {
                    if (showRecordingSnapshots) {
                        return true
                    } else {
                        return e.event !== '$snapshot'
                    }
                })
            },
        ],
    }),
    afterMount(({ values, actions }) => {
        values.posthog?.on('eventCaptured', (e) => {
            if (!e.uuid) {
                e.uuid = uuid()
            }
            actions.addEvent(e)
        })
    }),
    permanentlyMount(),
])
