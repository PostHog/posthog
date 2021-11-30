import { kea } from 'kea'
import api from 'lib/api'
import { posthogEvents } from 'lib/utils'
import { EventDefinition, SelectOption } from '~/types'
import { eventDefinitionsModelType } from './eventDefinitionsModelType'
import { propertyDefinitionsModel } from './propertyDefinitionsModel'
import { teamLogic } from 'scenes/teamLogic'

export interface EventDefinitionStorage {
    count: number
    next: null | string
    results: EventDefinition[]
}

interface EventsGroupedInterface {
    label: string
    options: SelectOption[]
}

export const eventDefinitionsModel = kea<eventDefinitionsModelType<EventDefinitionStorage, EventsGroupedInterface>>({
    path: ['models', 'eventDefinitionsModel'],
    actions: () => ({
        updateDescription: (id: string, description: string | null, type: string) => ({ id, description, type }),
        updateEventDefinition: (eventDefinition: EventDefinition) => ({ eventDefinition }),
    }),
    loaders: ({ values }) => ({
        eventStorage: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                loadEventDefinitions: async (initial?: boolean) => {
                    const url = initial
                        ? `api/projects/${teamLogic.values.currentTeamId}/event_definitions/?limit=5000`
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
            },
        ],
    }),
    reducers: () => ({
        eventStorage: [
            { results: [], next: null, count: 0 } as EventDefinitionStorage,
            {
                updateEventDefinition: (state, { eventDefinition }) => ({
                    count: state.count,
                    results: state.results.map((p) => (eventDefinition.id === p.id ? eventDefinition : p)),
                    next: state.next,
                }),
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
                actions.updateEventDefinition(response)
            } else {
                propertyDefinitionsModel.actions.updatePropertyDefinition(response)
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
        customEvents: [
            (s) => [s.eventDefinitions],
            (eventDefinitions): EventDefinition[] =>
                eventDefinitions.filter((definition) => !definition.name.startsWith('$')),
        ],
        customEventNames: [
            (s) => [s.eventNames],
            (eventNames): string[] => eventNames.filter((event) => !event.startsWith('$')),
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
