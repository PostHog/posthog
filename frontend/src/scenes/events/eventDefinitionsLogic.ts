import { kea } from 'kea'
import api from 'lib/api'
import { posthogEvents } from 'lib/utils'
import { EventDefinition, SelectOption } from '~/types'
import { eventDefinitionsLogicType } from './eventDefinitionsLogicType'

interface EventDefinitionStorage {
    count: number
    next: null | string
    results: EventDefinition[]
}

interface EventsGroupedInterface {
    label: string
    options: SelectOption[]
}

export const eventDefinitionsLogic = kea<
    eventDefinitionsLogicType<EventDefinitionStorage, EventDefinition, EventsGroupedInterface, SelectOption>
>({
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
                    const url = initial ? 'api/projects/@current/event_definitions/' : values.eventStorage.next
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
            (eventStorage: EventDefinitionStorage, eventStorageLoading: boolean): boolean =>
                !eventStorageLoading && !eventStorage.next,
        ],
        eventDefinitions: [
            (s) => [s.eventStorage],
            (eventStorage: EventDefinitionStorage): EventDefinition[] => eventStorage.results,
        ],
        eventNames: [
            // TODO: This can be improved for performance by enabling downstream components to use `eventDefinitions` directly and getting rid of this selector.
            (s) => [s.eventDefinitions],
            (eventDefinitions: EventDefinition[]): string[] => eventDefinitions.map((definition) => definition.name),
        ],
        customEventNames: [
            (s) => [s.eventNames],
            (eventNames: string[]): string[] => eventNames.filter((event) => !event.startsWith('!')),
        ],
        eventNamesGrouped: [
            // TODO: This can be improved for performance by enabling downstream components to use `eventDefinitions` directly and getting rid of this selector.
            (s) => [s.eventDefinitions],
            (eventNames: string[]): EventsGroupedInterface[] => {
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
