import { kea } from 'kea'
import api from 'lib/api'
import { posthogEvents } from 'lib/utils'
import { EventDefinition, SelectOption } from '~/types'
import { eventDefinitionsModelType } from './eventDefinitionsModelType'
import { propertyDefinitionsModel } from './propertyDefinitionsModel'

interface EventDefinitionStorage {
    count: number
    next: null | string
    results: EventDefinition[]
}

interface EventsGroupedInterface {
    label: string
    options: SelectOption[]
}

export const eventDefinitionsModel = kea<eventDefinitionsModelType<EventDefinitionStorage, EventsGroupedInterface>>({
    actions: () => ({
        updateDescription: (id: string, description: string | null, type: string) => ({ id, description, type }),
        setEventDefinitions: (event) => ({ event }),
    }),
    loaders: ({ values }) => ({
        eventStorage: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                loadEventDefinitions: async (initial?: boolean) => {
                    const url = initial
                        ? 'api/projects/@current/event_definitions/?limit=5000'
                        : values.eventStorage.next
                    if (!url) {
                        throw new Error('Incorrect call to eventDefinitionsModel.loadEventDefinitions')
                    }
                    const eventStorage = await api.get(url)
                    return {
                        count: eventStorage.count,
                        results: [...values.eventStorage.results, ...eventStorage.results],
                        next: eventStorage.next,
                    }
                },
                // setEventDefinitions: (event) => {
                //     const updatedDefinitions = values.eventStorage.results.map((e) => (event.id === e.id ? event : e))
                //     return {
                //         count: values.eventStorage.count,
                //         results: updatedDefinitions,
                //         next: values.eventStorage.next,
                //     }
                // },
            },
        ],
    }),
    reducers: () => ({
        eventStorage: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                setEventDefinitions: (state, { event }) => {
                    const updatedDefinitions = state.results.map((p) => (event.id === p.id ? { ...event } : { ...p }))
                    return {
                        count: state.count,
                        results: updatedDefinitions,
                        next: state.next,
                    }
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
        updateDescription: async ({ id, description, type }) => {
            const response = await api.update(`api/projects/@current/${type}_definitions/${id}`, { description })
            if (type === 'event') {
                actions.setEventDefinitions(response)
            } else {
                propertyDefinitionsModel.actions.setPropertyDefinitions(response)
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
            (eventStorage, eventStorageLoading): boolean => !eventStorageLoading && !eventStorage.next,
        ],
        eventDefinitions: [(s) => [s.eventStorage], (eventStorage): EventDefinition[] => eventStorage.results],
        eventNames: [
            (s) => [s.eventDefinitions],
            (eventDefinitions): string[] => eventDefinitions.map((definition) => definition.name),
        ],
        customEventNames: [
            (s) => [s.eventNames],
            (eventNames): string[] => eventNames.filter((event) => !event.startsWith('!')),
        ],
        eventNamesGrouped: [
            (s) => [s.eventNames],
            (eventNames): EventsGroupedInterface[] => {
                const data: EventsGroupedInterface[] = [
                    { label: 'Custom events', options: [] },
                    { label: 'PostHog events', options: [] },
                ]

                eventNames.forEach((name: string) => {
                    const format = { label: name, value: name }
                    if (posthogEvents.includes(name)) {
                        return data[1].options.push(format)
                    }
                    data[0].options.push(format)
                })

                return data
            },
        ],
    },
})
