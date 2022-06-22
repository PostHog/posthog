import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { PropertyDefinition } from '~/types'
import api from 'lib/api'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import {
    normalizePropertyDefinitionEndpointUrl,
    PropertyDefinitionsPaginatedResponse,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import type { eventPropertyDefinitionsTableLogicType } from './eventPropertyDefinitionsTableLogicType'
import { objectsEqual } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { loaders } from 'kea-loaders'

export interface Filters {
    property: string
}

function cleanFilters(filter: Partial<Filters>): Filters {
    return {
        property: '',
        ...filter,
    }
}

export const EVENT_PROPERTY_DEFINITIONS_PER_PAGE = 50

export interface EventPropertyDefinitionsTableLogicProps {
    key: string
}

export const eventPropertyDefinitionsTableLogic = kea<eventPropertyDefinitionsTableLogicType>([
    path(['scenes', 'data-management', 'event-properties', 'eventPropertyDefinitionsTableLogic']),
    props({} as EventPropertyDefinitionsTableLogicProps),
    key((props) => props.key || 'scene'),
    actions({
        loadEventPropertyDefinitions: (url: string | null = '') => ({
            url,
        }),
        setFilters: (filters: Partial<Filters>) => ({ filters }),
        setHoveredDefinition: (definitionKey: string | null) => ({ definitionKey }),
        setOpenedDefinition: (id: string | null) => ({ id }),
        setLocalEventPropertyDefinition: (definition: PropertyDefinition) => ({ definition }),
    }),
    reducers({
        filters: [
            {
                property: '',
            } as Filters,
            {
                setFilters: (state, { filters }) => ({
                    ...state,
                    ...filters,
                }),
            },
        ],
        hoveredDefinition: [
            null as string | null,
            {
                setHoveredDefinition: (_, { definitionKey }) => definitionKey,
            },
        ],
    }),
    loaders(({ values, cache }) => ({
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
                    cache.propertiesStartTime = performance.now()
                    await breakpoint(200)
                    const response = await api.get(url)
                    breakpoint()

                    const currentUrl = `${normalizePropertyDefinitionEndpointUrl(url)}`
                    cache.apiCache = {
                        ...(cache.apiCache ?? {}),
                        [currentUrl]: {
                            ...response,
                            previous: normalizePropertyDefinitionEndpointUrl(response.previous),
                            next: normalizePropertyDefinitionEndpointUrl(response.next),
                            current: currentUrl,
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
    })),
    selectors(({ cache }) => ({
        // Expose for testing
        apiCache: [() => [], () => cache.apiCache],
    })),
    listeners(({ actions, values, cache }) => ({
        setFilters: () => {
            actions.loadEventPropertyDefinitions(
                normalizePropertyDefinitionEndpointUrl(
                    values.eventPropertyDefinitions.current,
                    {
                        search: values.filters.property,
                    },
                    true
                )
            )
        },
        loadEventPropertyDefinitionsSuccess: () => {
            if (cache.propertiesStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventPropertyDefinitionsPageLoadSucceeded(
                        performance.now() - cache.propertiesStartTime,
                        values.eventPropertyDefinitions.results.length
                    )
                cache.propertiesStartTime = undefined
            }
        },
        loadEventPropertyDefinitionsFailure: ({ error }) => {
            if (cache.propertiesStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventPropertyDefinitionsPageLoadFailed(
                        performance.now() - cache.propertiesStartTime,
                        error ?? 'There was an unknown error fetching property definitions.'
                    )
                cache.propertiesStartTime = undefined
            }
        },
    })),
    urlToAction(({ actions, values }) => ({
        '/data-management/event-properties': (_, searchParams) => {
            if (!objectsEqual(cleanFilters(values.filters), cleanFilters(router.values.searchParams))) {
                actions.setFilters(searchParams as Filters)
            } else if (!values.eventPropertyDefinitions.results.length && !values.eventPropertyDefinitionsLoading) {
                actions.loadEventPropertyDefinitions()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(nextValues, urlValues)) {
                return [router.values.location.pathname, nextValues]
            }
        },
    })),
])
