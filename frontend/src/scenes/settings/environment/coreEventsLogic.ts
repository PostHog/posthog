import { actions, connect, kea, listeners, path, selectors } from 'kea'

import { teamLogic } from 'scenes/teamLogic'

import { CoreEvent } from '~/queries/schema/schema-general'

import type { coreEventsLogicType } from './coreEventsLogicType'

export const coreEventsLogic = kea<coreEventsLogicType>([
    path(['scenes', 'settings', 'environment', 'coreEventsLogic']),
    connect({
        values: [teamLogic, ['currentTeam']],
        actions: [teamLogic, ['updateCurrentTeam']],
    }),
    actions({
        addCoreEvent: (event: CoreEvent) => ({ event }),
        updateCoreEvent: (event: CoreEvent) => ({ event }),
        removeCoreEvent: (eventId: string) => ({ eventId }),
    }),
    selectors({
        coreEvents: [
            (s) => [s.currentTeam],
            (currentTeam): CoreEvent[] => {
                return (currentTeam?.core_events_config?.core_events as CoreEvent[]) || []
            },
        ],
    }),
    listeners(({ values, actions }) => ({
        addCoreEvent: ({ event }) => {
            const existingEvents = values.coreEvents
            const newEvents = [...existingEvents, event]
            actions.updateCurrentTeam({
                core_events_config: {
                    core_events: newEvents,
                },
            })
        },
        updateCoreEvent: ({ event }) => {
            const existingEvents = values.coreEvents
            const newEvents = existingEvents.map((e) => (e.id === event.id ? event : e))
            actions.updateCurrentTeam({
                core_events_config: {
                    core_events: newEvents,
                },
            })
        },
        removeCoreEvent: ({ eventId }) => {
            const existingEvents = values.coreEvents
            const newEvents = existingEvents.filter((e) => e.id !== eventId)
            actions.updateCurrentTeam({
                core_events_config: {
                    core_events: newEvents,
                },
            })
        },
    })),
])
