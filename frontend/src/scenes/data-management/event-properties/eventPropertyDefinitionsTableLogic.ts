import { kea } from 'kea'
import { PropertyDefinition } from '~/types'
import api from 'lib/api'
import { combineUrl, router } from 'kea-router'
import {
    normalizePropertyDefinitionEndpointUrl,
    PropertyDefinitionsPaginatedResponse,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { eventPropertyDefinitionsTableLogicType } from './eventPropertyDefinitionsTableLogicType'
import { objectsEqual } from 'lib/utils'

interface Filters {
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

export const eventPropertyDefinitionsTableLogic = kea<
    eventPropertyDefinitionsTableLogicType<EventPropertyDefinitionsTableLogicProps, Filters>
>({
    path: (key: string) => ['scenes', 'data-management', 'event-properties', 'eventPropertyDefinitionsTableLogic', key],
    props: {} as EventPropertyDefinitionsTableLogicProps,
    key: (props) => props.key || 'scene',
    actions: {
        loadEventPropertyDefinitions: (url: string | null = '', orderIdsFirst: string[] = []) => ({
            url,
            orderIdsFirst,
        }),
        setFilters: (filters: Partial<Filters>) => ({ filters }),
        setHoveredDefinition: (definitionKey: string | null) => ({ definitionKey }),
        setOpenedDefinition: (id: string | null) => ({ id }),
        setLocalEventPropertyDefinition: (definition: PropertyDefinition) => ({ definition }),
    },
    reducers: {
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
                loadEventPropertyDefinitions: async ({ url, orderIdsFirst }, breakpoint) => {
                    if (url && url in (cache.apiCache ?? {})) {
                        return cache.apiCache[url]
                    }

                    if (!url) {
                        url = api.propertyDefinitions.determineListEndpoint({
                            order_ids_first: orderIdsFirst,
                        })
                    }
                    console.log('TRIGGER', url)
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
    }),
    selectors: ({ cache }) => ({
        // Expose for testing
        apiCache: [() => [], () => cache.apiCache],
    }),
    listeners: ({ actions, values }) => ({
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
    }),
    urlToAction: ({ actions, values }) => ({
        '/data-management/event-properties': (_, searchParams) => {
            if (!objectsEqual(cleanFilters(values.filters), cleanFilters(router.values.searchParams))) {
                actions.setFilters(searchParams as Filters)
            } else if (!values.eventPropertyDefinitions.results.length && !values.eventPropertyDefinitionsLoading) {
                actions.loadEventPropertyDefinitions()
            }
        },
        '/data-management/event-properties/:id': ({ id }) => {
            if (!values.eventPropertyDefinitions.results.length && !values.eventPropertyDefinitionsLoading) {
                actions.loadEventPropertyDefinitions(null, id ? [id] : [])
            }
            if (id) {
                actions.setOpenedDefinition(id)
            }
        },
    }),
    actionToUrl: ({ values }) => ({
        setFilters: () => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(nextValues, urlValues)) {
                return [router.values.location.pathname, nextValues]
            }
        },
    }),
})
