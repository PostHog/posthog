import { kea } from 'kea'
import { AnyPropertyFilter, EventDefinition, PropertyDefinition } from '~/types'
import { eventDefinitionsTableLogicType } from './eventDefinitionsTableLogicType'
import api, { PaginatedResponse } from 'lib/api'
import { keyMappingKeys } from 'lib/components/PropertyKeyInfo'
import { combineUrl } from 'kea-router'

interface EventDefinitionsPaginatedResponse extends PaginatedResponse<EventDefinition> {
    current?: string
    count?: number
    page?: number
}

export interface PropertyDefinitionsPaginatedResponse extends PaginatedResponse<PropertyDefinition> {
    current?: string
    count?: number
    page?: number
}

interface Filters {
    event: string
    properties: AnyPropertyFilter[]
}

export const EVENT_DEFINITIONS_PER_PAGE = 50
export const PROPERTY_DEFINITIONS_PER_EVENT = 5

export function createDefinitionKey(event?: EventDefinition, property?: PropertyDefinition): string {
    return `${event?.id ?? 'event'}-${property?.id ?? 'property'}`
}

function normalizePropertyDefinitionEndpointUrl(url: string | null): string | null {
    if (!url) {
        return null
    }
    return api.propertyDefinitions.determineListEndpoint(combineUrl(url).searchParams)
}

export interface EventDefinitionsTableLogicProps {
    key: string
}

export const eventDefinitionsTableLogic = kea<
    eventDefinitionsTableLogicType<
        EventDefinitionsPaginatedResponse,
        EventDefinitionsTableLogicProps,
        Filters,
        PropertyDefinitionsPaginatedResponse
    >
>({
    path: (key) => ['scenes', 'data-management', 'events', 'eventDefinitionsTableLogic', key],
    props: {} as EventDefinitionsTableLogicProps,
    key: (props) => props.key || 'scene',
    actions: {
        loadEventDefinitions: (url: string | null = '', orderIdsFirst: string[] = []) => ({ url, orderIdsFirst }),
        loadEventExample: (definition: EventDefinition) => ({ definition }),
        loadPropertiesForEvent: (definition: EventDefinition, url: string | null = '') => ({ definition, url }),
        setFilters: (filters: Filters) => ({ filters }),
        setHoveredDefinition: (definitionKey: string | null) => ({ definitionKey }),
        setOpenedDefinition: (id: string | null) => ({ id }),
        setLocalEventDefinition: (definition: EventDefinition) => ({ definition }),
        setLocalPropertyDefinition: (event: EventDefinition, definition: PropertyDefinition) => ({ event, definition }),
        setEventDefinitionPropertiesLoading: (ids: string[]) => ({ ids }),
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
        eventDefinitionPropertiesLoading: [
            [] as string[],
            {
                setEventDefinitionPropertiesLoading: (_, { ids }) => ids ?? [],
            },
        ],
    },
    loaders: ({ values, cache, actions }) => ({
        eventDefinitions: [
            {
                count: 0,
                next: undefined,
                current: undefined,
                previous: undefined,
                results: [],
            } as EventDefinitionsPaginatedResponse,
            {
                loadEventDefinitions: async ({ url, orderIdsFirst }, breakpoint) => {
                    if (url && url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }

                    if (!url) {
                        url = api.eventDefinitions.determineListEndpoint({
                            order_ids_first: orderIdsFirst,
                        })
                    }
                    const response = await api.get(url)
                    breakpoint()

                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [url]: {
                            ...response,
                            current: url,
                            page:
                                Math.floor((combineUrl(url).searchParams.offset ?? 0) / EVENT_DEFINITIONS_PER_PAGE) + 1,
                        },
                    }
                    return cache.apiCache[url]
                },
                setLocalEventDefinition: ({ definition }) => {
                    if (!values.eventDefinitions.current) {
                        return values.eventDefinitions
                    }
                    // Update cache as well
                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [values.eventDefinitions.current]: {
                            ...values.eventDefinitions,
                            results: values.eventDefinitions.results.map((d) =>
                                d.id === definition.id ? definition : d
                            ),
                        },
                    }
                    return cache.apiCache[values.eventDefinitions.current]
                },
            },
        ],
        eventPropertiesCacheMap: [
            {} as Record<string, PropertyDefinitionsPaginatedResponse>,
            {
                loadPropertiesForEvent: async ({ definition, url }, breakpoint) => {
                    if (url && url in (cache.apiCache ?? {})) {
                        return {
                            ...values.eventPropertiesCacheMap,
                            [definition.id]: cache.apiCache[url],
                        }
                    }

                    if (!url) {
                        url = api.propertyDefinitions.determineListEndpoint({
                            event_names: [definition.name],
                            excluded_properties: keyMappingKeys,
                            is_event_property: true,
                            limit: PROPERTY_DEFINITIONS_PER_EVENT,
                        })
                    }
                    actions.setEventDefinitionPropertiesLoading(
                        Array.from([...values.eventDefinitionPropertiesLoading, definition.id])
                    )
                    const response = await api.get(url)
                    breakpoint()

                    // Fetch one event as example and cache
                    let exampleEventProperties: Record<string, string>
                    const exampleUrl = api.events.determineListEndpoint({ event: definition.name }, 1)
                    if (exampleUrl && exampleUrl in (cache.apiCache ?? {})) {
                        exampleEventProperties = cache.apiCache[exampleUrl]
                    } else {
                        exampleEventProperties = (await api.get(exampleUrl))?.results?.[0].properties ?? {}
                        cache.apiCache = {
                            ...(cache.apiCache ?? {}),
                            [exampleUrl]: exampleEventProperties,
                        }
                    }

                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [url]: {
                            count: response.count,
                            previous: normalizePropertyDefinitionEndpointUrl(response.previous),
                            next: normalizePropertyDefinitionEndpointUrl(response.next),
                            current: url,
                            page:
                                Math.floor(
                                    (combineUrl(url).searchParams.offset ?? 0) / PROPERTY_DEFINITIONS_PER_EVENT
                                ) + 1,
                            results: response.results.map((prop: PropertyDefinition) => ({
                                ...prop,
                                example: exampleEventProperties?.[prop.name]?.toString(),
                            })),
                        },
                    }

                    actions.setEventDefinitionPropertiesLoading(
                        values.eventDefinitionPropertiesLoading.filter((loadingId) => loadingId != definition.id)
                    )
                    return {
                        ...values.eventPropertiesCacheMap,
                        [definition.id]: cache.apiCache[url],
                    }
                },
                setLocalPropertyDefinition: ({ event, definition }) => {
                    if (!values.eventPropertiesCacheMap?.[event.id]?.current) {
                        return values.eventPropertiesCacheMap
                    }
                    // Update cache as well
                    const eventCacheKey = values.eventPropertiesCacheMap[event.id].current as string
                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [eventCacheKey]: {
                            ...values.eventPropertiesCacheMap[event.id],
                            results: values.eventPropertiesCacheMap[event.id].results.map((p) =>
                                p.id === definition.id ? definition : p
                            ),
                        },
                    }

                    return {
                        ...values.eventPropertiesCacheMap,
                        [event.id]: cache.apiCache[eventCacheKey],
                    }
                },
            },
        ],
    }),
    selectors: ({ cache }) => ({
        // Expose for testing
        apiCache: [() => [], () => cache.apiCache],
    }),
    urlToAction: ({ actions, values }) => ({
        '/data-management/events': (_, searchParams) => {
            actions.setFilters(searchParams as Filters)
            if (!values.eventDefinitions.results.length && !values.eventDefinitionsLoading) {
                actions.loadEventDefinitions()
            }
        },
        '/data-management/events/:id': ({ id }) => {
            if (!values.eventDefinitions.results.length && !values.eventDefinitionsLoading) {
                actions.loadEventDefinitions(null, id ? [id] : [])
            }
            if (id) {
                actions.setOpenedDefinition(id)
            }
        },
    }),
})
