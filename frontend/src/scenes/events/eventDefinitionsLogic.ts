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
                loadEventDefinitionsSuccess: (state, { eventStorage }) => {
                    return {
                        count: eventStorage.count,
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
                loadEventDefinitions: async (initial?: boolean) => {
                    const url = initial ? 'api/projects/@current/event_definitions/?limit=2' : values.eventStorage.next
                    if (!url) {
                        throw new Error('Incorrect call to eventDefinitionsLogic.loadEventDefinitions')
                    }
                    return await api.get(url)
                },
            },
        ],
    }),
    listeners: ({ actions }) => ({
        loadEventDefinitionsSuccess: ({ eventStorage }) => {
            if (eventStorage.next) {
                actions.loadEventDefinitions()
            }
        },
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadEventDefinitions(true)
        },
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
