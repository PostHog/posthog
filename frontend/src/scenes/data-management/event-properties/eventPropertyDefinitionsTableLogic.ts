import { kea } from 'kea'
import { AnyPropertyFilter, PropertyDefinition } from '~/types'
import api from 'lib/api'
import { combineUrl } from 'kea-router'
import { PropertyDefinitionsPaginatedResponse } from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { eventPropertyDefinitionsTableLogicType } from './eventPropertyDefinitionsTableLogicType'

interface Filters {
    event: string
    properties: AnyPropertyFilter[]
}

export const EVENT_PROPERTY_DEFINITIONS_PER_PAGE = 50

export interface EventPropertyDefinitionsTableLogicProps {
    key: string
    syncWithUrl?: boolean
}

export const eventPropertyDefinitionsTableLogic = kea<
    eventPropertyDefinitionsTableLogicType<EventPropertyDefinitionsTableLogicProps, Filters>
>({
    path: (key: string) => ['scenes', 'data-management', 'event-properties', 'eventPropertyDefinitionsTableLogic', key],
    props: {} as EventPropertyDefinitionsTableLogicProps,
    key: (props) => props.key || 'scene',
    actions: {
        loadEventPropertyDefinitions: (url: string | null = '') => ({ url }),
        setFilters: (filters: Filters) => ({ filters }),
        setHoveredDefinition: (definitionKey: string | null) => ({ definitionKey }),
        setOpenedDefinition: (id: string | null) => ({ id }),
        setLocalPropertyDefinition: (definition: PropertyDefinition) => ({ definition }),
    },
    reducers: {
        filters: [
            {
                event: '',
                properties: [],
            } as Filters,
            {
                setFilters: (_, { filters }) => filters,
            },
        ],
        hoveredDefinition: [
            null as string | null,
            {
                setHoveredDefinition: (_, { definitionKey }) => definitionKey,
            },
        ],
        openedDefinitionId: [
            null as string | null,
            {
                setOpenedDefinition: (_, { id }) => id,
            },
        ],
    },
    loaders: ({ values, cache }) => ({
        eventPropertyDefinitions: [
            {
                count: 0,
                next: undefined,
                current: undefined,
                previous: undefined,
                results: [],
            } as PropertyDefinitionsPaginatedResponse,
            {
                loadEventPropertyDefinitions: async ({ url }, breakpoint) => {
                    if (url && url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }

                    if (!url) {
                        url = api.propertyDefinitions.determineListEndpoint({})
                    }
                    const response = await api.get(url)
                    breakpoint()

                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [url]: {
                            ...response,
                            current: url,
                            page:
                                Math.floor(
                                    (combineUrl(url).searchParams.offset ?? 0) / EVENT_PROPERTY_DEFINITIONS_PER_PAGE
                                ) + 1,
                        },
                    }
                    return cache.apiCache[url]
                },
                setLocalEventPropertyDefinition: ({ definition }) => {
                    if (!values.eventPropertyDefinitions.current) {
                        return values.eventPropertyDefinitions
                    }
                    // Update cache as well
                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [values.eventPropertyDefinitions.current]: {
                            ...values.eventPropertyDefinitions,
                            results: values.eventPropertyDefinitions.results.map((d) =>
                                d.id === definition.id ? definition : d
                            ),
                        },
                    }
                    return cache.apiCache[values.eventPropertyDefinitions.current]
                },
            },
        ],
    }),
    selectors: ({ cache }) => ({
        // Expose for testing
        apiCache: [() => [], () => cache.apiCache],
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/events/properties': (_, searchParams) => {
            if (props.syncWithUrl) {
                actions.setFilters(searchParams as Filters)
                if (!values.eventPropertyDefinitions.results.length && !values.eventPropertyDefinitionsLoading) {
                    actions.loadEventPropertyDefinitions()
                }
            }
        },
        '/events/properties/:id': ({ id }) => {
            if (props.syncWithUrl) {
                if (!values.eventPropertyDefinitions.results.length && !values.eventPropertyDefinitionsLoading) {
                    actions.loadEventPropertyDefinitions()
                }
                if (id) {
                    actions.setOpenedDefinition(id)
                }
            }
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            if (!values.eventPropertyDefinitions.results.length && !values.eventPropertyDefinitionsLoading) {
                actions.loadEventPropertyDefinitions()
            }
        },
    }),
})
