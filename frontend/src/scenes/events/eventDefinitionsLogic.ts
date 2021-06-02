import { kea } from 'kea'
import { insightDataCachingLogic } from 'lib/logic/insightDataCachingLogic'
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
    connect: {
        actions: [insightDataCachingLogic, ['maybeLoadData', 'finishLoading']],
        values: [insightDataCachingLogic, ['cachedData', 'cacheLoading']],
    },
    actions: {
        eventDefinitionsUpdated: true,
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.maybeLoadData({
                key: 'eventDefinitions',
                endpoint: 'api/projects/@current/event_definitions/?limit=5000',
                paginated: true,
            })
        },
    }),
    selectors: {
        eventStorage: [
            (s) => [s.cachedData],
            (cachedData): EventDefinitionStorage => {
                if (cachedData['eventDefinitions']) {
                    return cachedData['eventDefinitions']
                }
                return { results: [], next: null, count: 0 }
            },
        ],
        loaded: [
            // Whether *all* the event definitions are fully loaded
            (s) => [s.eventStorage, s.cacheLoading],
            (eventStorage, cacheLoading): boolean => !cacheLoading['eventDefinitions'] && !eventStorage.next,
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
    listeners: ({ actions }) => ({
        finishLoading: ({ key }) => {
            if (key === 'eventDefinitions') {
                actions.eventDefinitionsUpdated()
            }
        },
    }),
})
