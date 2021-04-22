import { kea } from 'kea'
import api from 'lib/api'
import { EventDefinition } from '~/types'
import { eventDefinitionsLogicType } from './eventDefinitionsLogicType'

interface EventDefinitionStorage {
    count: number
    next: null | string
    results: EventDefinition[]
}

export const eventDefinitionsLogic = kea<eventDefinitionsLogicType<EventDefinitionStorage>>({
    reducers: {
        eventStorage: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                loadNextEventDefinitions: (state, { eventStorage }) => {
                    return {
                        ...state,
                        results: [...state.results, ...eventStorage.results],
                        next: eventStorage.next,
                    }
                },
            },
        ],
    },
    loaders: ({ values }) => ({
        eventStorage: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                loadEventDefinitions: async () => await api.get('api/projects/@current/event_definitions/'),
                loadNextEventDefinitions: async () => await api.get(values.eventStorage.next),
            },
        ],
    }),
    listeners: ({ actions }) => ({
        loadEventDefinitionsSuccess: ({ eventStorage }) => {
            if (eventStorage.next) {
                actions.loadNextEventDefinitions()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: [actions.loadNextEventDefinitions],
    }),
    selectors: {
        loaded: [
            // Whether *all* the event definitions are fully loaded
            (s) => [s.eventStorage, s.eventStorageLoading],
            (eventStorage: EventDefinitionStorage, eventStorageLoading: boolean) =>
                !eventStorageLoading && !eventStorage.next,
        ],
        eventProperties: [(s) => [s.eventStorage], (eventStorage: EventDefinitionStorage) => eventStorage.results],
    },
})
