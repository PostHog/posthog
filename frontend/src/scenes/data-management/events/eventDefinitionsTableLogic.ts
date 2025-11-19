import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'

import api, { PaginatedResponse } from 'lib/api'
import { convertPropertyGroupToProperties } from 'lib/components/PropertyFilters/utils'
import { EVENT_DEFINITIONS_PER_PAGE, PROPERTY_DEFINITIONS_PER_EVENT } from 'lib/constants'
import { parseTagsFilter } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'

import { AnyPropertyFilter, EventDefinition, EventDefinitionType, PropertyDefinition } from '~/types'

import type { eventDefinitionsTableLogicType } from './eventDefinitionsTableLogicType'

export interface EventDefinitionsPaginatedResponse extends PaginatedResponse<EventDefinition> {
    current?: string
    count?: number
    page?: number
}

export interface PropertyDefinitionsPaginatedResponse extends PaginatedResponse<PropertyDefinition> {
    current?: string
    count?: number
    page?: number
}

export interface Filters {
    event: string
    properties: AnyPropertyFilter[]
    event_type: EventDefinitionType
    ordering?: string
    tags?: string[]
}

const DEFAULT_FILTERS: Filters = {
    event: '',
    properties: [],
    event_type: EventDefinitionType.Event,
    ordering: 'event',
    tags: undefined,
}

export function createDefinitionKey(event?: EventDefinition, property?: PropertyDefinition): string {
    return `${event?.id ?? 'event'}-${property?.id ?? 'property'}`
}

export function normalizePropertyDefinitionEndpointUrl(
    url: string | null | undefined,
    searchParams: Record<string, any> = {},
    full: boolean = false
): string | null {
    if (!full && !url) {
        return null
    }
    return api.propertyDefinitions.determineListEndpoint({
        ...(url ? combineUrl(url).searchParams : {}),
        ...searchParams,
    })
}

function normalizeEventDefinitionEndpointUrl({
    url,
    searchParams = {},
    full = false,
    eventTypeFilter = EventDefinitionType.Event,
}: {
    url?: string | null | undefined
    searchParams?: Record<string, any>
    full?: boolean
    eventTypeFilter?: EventDefinitionType
}): string | null {
    if (!full && !url) {
        return null
    }
    const params = {
        ...(url
            ? {
                  ...combineUrl(url).searchParams,
                  event_type: eventTypeFilter,
              }
            : {}),
        ...searchParams,
    }
    return api.eventDefinitions.determineListEndpoint(params)
}

export interface EventDefinitionsTableLogicProps {
    key: string
}

export const eventDefinitionsTableLogic = kea<eventDefinitionsTableLogicType>([
    path((key) => ['scenes', 'data-management', 'events', 'eventDefinitionsTableLogic', key]),
    props({} as EventDefinitionsTableLogicProps),
    key((props) => props.key || 'scene'),
    actions({
        loadEventDefinitions: (url: string | null = '') => ({ url }),
        loadEventExample: (definition: EventDefinition) => ({ definition }),
        loadPropertiesForEvent: (definition: EventDefinition, url: string | null = '') => ({ definition, url }),
        setFilters: (filters: Partial<Filters>) => ({ filters }),
        setLocalEventDefinition: (definition: EventDefinition) => ({ definition }),
        setLocalPropertyDefinition: (event: EventDefinition, definition: PropertyDefinition) => ({ event, definition }),
        setEventDefinitionPropertiesLoading: (ids: string[]) => ({ ids }),
    }),
    reducers({
        filters: [
            DEFAULT_FILTERS,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                    properties: convertPropertyGroupToProperties(filters.properties) ?? [],
                }),
            },
        ],
        eventDefinitionPropertiesLoading: [
            [] as string[],
            {
                setEventDefinitionPropertiesLoading: (_, { ids }) => ids ?? [],
            },
        ],
    }),
    loaders(({ values, cache, actions }) => ({
        eventDefinitions: [
            {
                count: 0,
                next: undefined,
                current: undefined,
                previous: undefined,
                results: [],
            } as EventDefinitionsPaginatedResponse,
            {
                loadEventDefinitions: async ({ url: _url }, breakpoint) => {
                    let url = _url

                    if (!url) {
                        url = api.eventDefinitions.determineListEndpoint(values.paramsFromFilters)
                    }

                    if (url && url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }

                    await breakpoint(200)
                    cache.eventsStartTime = performance.now()
                    const response = await api.get(url)
                    breakpoint()

                    const result = {
                        ...response,
                        previous: normalizeEventDefinitionEndpointUrl({
                            url: response.previous,
                            eventTypeFilter: values.filters.event_type,
                        }),
                        next: normalizeEventDefinitionEndpointUrl({
                            url: response.next,
                            eventTypeFilter: values.filters.event_type,
                        }),
                        current: url,
                        page: Math.floor((combineUrl(url).searchParams.offset ?? 0) / EVENT_DEFINITIONS_PER_PAGE) + 1,
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [url]: result,
                    }

                    return result
                },
                setLocalEventDefinition: ({ definition }) => {
                    if (!values.eventDefinitions.current) {
                        return values.eventDefinitions
                    }
                    const result = {
                        ...values.eventDefinitions,
                        results: values.eventDefinitions.results.map((d) => (d.id === definition.id ? definition : d)),
                    }

                    // Update cache
                    cache.apiCache = {
                        ...cache.apiCache,
                        [values.eventDefinitions.current]: result,
                    }

                    return result
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
                            exclude_core_properties: true,
                            filter_by_event_names: true,
                            is_feature_flag: false,
                            limit: PROPERTY_DEFINITIONS_PER_EVENT,
                        })
                    }
                    actions.setEventDefinitionPropertiesLoading(
                        Array.from([...values.eventDefinitionPropertiesLoading, definition.id])
                    )
                    cache.propertiesStartTime = performance.now()
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
                            ...cache.apiCache,
                            [exampleUrl]: exampleEventProperties,
                        }
                    }

                    const currentUrl = `${normalizePropertyDefinitionEndpointUrl(url)}`
                    const propertyResult = {
                        count: response.count,
                        previous: normalizePropertyDefinitionEndpointUrl(response.previous),
                        next: normalizePropertyDefinitionEndpointUrl(response.next),
                        current: currentUrl,
                        page:
                            Math.floor(
                                (combineUrl(currentUrl).searchParams.offset ?? 0) / PROPERTY_DEFINITIONS_PER_EVENT
                            ) + 1,
                        results: response.results.map((prop: PropertyDefinition) => ({
                            ...prop,
                            example: exampleEventProperties?.[prop.name]?.toString(),
                        })),
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [currentUrl]: propertyResult,
                    }

                    actions.setEventDefinitionPropertiesLoading(
                        values.eventDefinitionPropertiesLoading.filter((loadingId) => loadingId != definition.id)
                    )
                    return {
                        ...values.eventPropertiesCacheMap,
                        [definition.id]: propertyResult,
                    }
                },
                setLocalPropertyDefinition: ({ event, definition }) => {
                    if (!values.eventPropertiesCacheMap?.[event.id]?.current) {
                        return values.eventPropertiesCacheMap
                    }
                    // Update cache as well
                    const eventCacheKey = values.eventPropertiesCacheMap[event.id].current as string
                    const updatedProperties = {
                        ...values.eventPropertiesCacheMap[event.id],
                        results: values.eventPropertiesCacheMap[event.id].results.map((p) =>
                            p.id === definition.id ? definition : p
                        ),
                    }

                    cache.apiCache = {
                        ...cache.apiCache,
                        [eventCacheKey]: updatedProperties,
                    }

                    return {
                        ...values.eventPropertiesCacheMap,
                        [event.id]: updatedProperties,
                    }
                },
            },
        ],
    })),
    selectors(() => ({
        // Convert filters to API params
        paramsFromFilters: [
            (s) => [s.filters],
            (filters: Filters) => {
                const params: Record<string, any> = {
                    search: filters.event,
                    ordering: filters.ordering,
                    event_type: filters.event_type,
                }
                if (filters.tags && filters.tags.length > 0) {
                    params.tags = JSON.stringify(filters.tags)
                }
                return params
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        setFilters: async () => {
            actions.loadEventDefinitions()
        },
        loadEventDefinitionsSuccess: () => {
            if (cache.eventsStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventDefinitionsPageLoadSucceeded(
                        performance.now() - cache.eventsStartTime,
                        values.eventDefinitions.results.length
                    )
                cache.eventsStartTime = undefined
            }
        },
        loadEventDefinitionsFailure: ({ error }) => {
            if (cache.eventsStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventDefinitionsPageLoadFailed(
                        performance.now() - cache.eventsStartTime,
                        error ?? 'There was an unknown error fetching event definitions.'
                    )
                cache.eventsStartTime = undefined
            }
        },
        loadPropertiesForEventSuccess: () => {
            if (cache.propertiesStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventDefinitionsPageNestedPropertiesLoadSucceeded(
                        performance.now() - cache.propertiesStartTime
                    )
                cache.propertiesStartTime = undefined
            }
        },
        loadPropertiesForEventFailure: ({ error }) => {
            if (cache.propertiesStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventDefinitionsPageNestedPropertiesLoadFailed(
                        performance.now() - cache.propertiesStartTime,
                        error ?? 'There was an unknown error fetching nested property definitions.'
                    )
                cache.propertiesStartTime = undefined
            }
        },
    })),
    urlToAction(({ actions }) => ({
        '/data-management/events': (_, searchParams) => {
            const { event, event_type, ordering, tags } = searchParams

            const filtersFromUrl: Filters = {
                ...DEFAULT_FILTERS,
                ...(event !== undefined && { event }),
                ...(event_type !== undefined && { event_type }),
                ...(ordering !== undefined && { ordering }),
                ...(parseTagsFilter(tags) !== undefined && { tags: parseTagsFilter(tags) }),
            }

            actions.setFilters(filtersFromUrl)
        },
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => [router.values.location.pathname, values.filters],
    })),
])
