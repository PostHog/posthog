import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { actionToUrl, combineUrl, router, urlToAction } from 'kea-router'
import api from 'lib/api'
import { EVENT_PROPERTY_DEFINITIONS_PER_PAGE } from 'lib/constants'
import { LemonSelectOption } from 'lib/lemon-ui/LemonSelect'
import { capitalizeFirstLetter, objectsEqual } from 'lib/utils'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import {
    normalizePropertyDefinitionEndpointUrl,
    PropertyDefinitionsPaginatedResponse,
} from 'scenes/data-management/events/eventDefinitionsTableLogic'
import { urls } from 'scenes/urls'

import { PropertyDefinition } from '~/types'

import { groupsModel } from '../../../models/groupsModel'
import type { propertyDefinitionsTableLogicType } from './propertyDefinitionsTableLogicType'

export interface Filters {
    property: string
    type: string
    group_type_index: number | null
}

function cleanFilters(filter: Partial<Filters>): Filters {
    return {
        property: '',
        type: 'event',
        group_type_index: null,
        ...filter,
    }
}

function removeDefaults(filter: Filters): Partial<Filters> {
    return {
        property: filter.property !== '' ? filter.property : undefined,
        type: filter.type !== 'event' ? filter.type : undefined,
        group_type_index: filter.group_type_index !== null ? filter.group_type_index : undefined,
    }
}

export interface PropertyDefinitionsTableLogicProps {
    key: string
}

export const propertyDefinitionsTableLogic = kea<propertyDefinitionsTableLogicType>([
    path(['scenes', 'data-management', 'properties', 'propertyDefinitionsTableLogic']),
    props({} as PropertyDefinitionsTableLogicProps),
    key((props) => props.key || 'scene'),
    connect(() => ({
        values: [groupsModel, ['groupTypes', 'aggregationLabel']],
    })),
    actions({
        loadPropertyDefinitions: (url: string | null = '') => ({
            url,
        }),
        setFilters: (filters: Partial<Filters>) => ({ filters }),
        setHoveredDefinition: (definitionKey: string | null) => ({ definitionKey }),
        setOpenedDefinition: (id: string | null) => ({ id }),
        setLocalPropertyDefinition: (definition: PropertyDefinition) => ({ definition }),
        setPropertyType: (propertyType: string) => ({ propertyType }),
    }),
    reducers({
        filters: [
            {
                property: '',
                type: 'event',
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
    selectors({
        propertyTypeOptions: [
            (s) => [s.groupTypes, s.aggregationLabel],
            (groupTypes, aggregationLabel) => {
                const groupChoices: Array<LemonSelectOption<string>> = Array.from(groupTypes.values()).map((type) => ({
                    label: `${capitalizeFirstLetter(aggregationLabel(type.group_type_index).singular)} properties`,
                    value: `group::${type.group_type_index}`,
                }))
                return [
                    { label: 'Event properties', value: 'event::' } as LemonSelectOption<string>,
                    { label: 'Person properties', value: 'person::' } as LemonSelectOption<string>,
                ].concat(groupChoices)
            },
        ],
    }),
    loaders(({ values, cache }) => ({
        propertyDefinitions: [
            {
                count: 0,
                next: undefined,
                current: undefined,
                previous: undefined,
                results: [],
            } as PropertyDefinitionsPaginatedResponse,
            {
                loadPropertyDefinitions: async ({ url }, breakpoint) => {
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
                        ...cache.apiCache,
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
                setLocalPropertyDefinition: ({ definition }) => {
                    if (!values.propertyDefinitions.current) {
                        return values.propertyDefinitions
                    }
                    // Update cache as well
                    cache.apiCache = {
                        ...cache.apiCache,
                        [values.propertyDefinitions.current]: {
                            ...values.propertyDefinitions,
                            results: values.propertyDefinitions.results.map((d) =>
                                d.id === definition.id ? definition : d
                            ),
                        },
                    }
                    return cache.apiCache[values.propertyDefinitions.current]
                },
            },
        ],
    })),
    listeners(({ actions, values, cache }) => ({
        setFilters: async (_, breakpoint) => {
            await breakpoint(500)
            actions.loadPropertyDefinitions(
                normalizePropertyDefinitionEndpointUrl(
                    values.propertyDefinitions.current,
                    {
                        offset: 0,
                        search: values.filters.property,
                        type: values.filters.type,
                        group_type_index: values.filters.group_type_index,
                    },
                    true
                )
            )
        },
        loadPropertyDefinitionsSuccess: () => {
            if (cache.propertiesStartTime !== undefined) {
                eventUsageLogic
                    .findMounted()
                    ?.actions.reportDataManagementEventPropertyDefinitionsPageLoadSucceeded(
                        performance.now() - cache.propertiesStartTime,
                        values.propertyDefinitions.results.length
                    )
                cache.propertiesStartTime = undefined
            }
        },
        loadPropertyDefinitionsFailure: ({ error }) => {
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
        setPropertyType: ({ propertyType }) => {
            const [type, index] = propertyType.split('::')
            actions.setFilters({
                type: type,
                group_type_index: index ? +index : null,
            })
        },
    })),
    urlToAction(({ actions, values }) => ({
        [urls.propertyDefinitions()]: (_, searchParams) => {
            if (values.propertyDefinitionsLoading) {
                return
            }
            if (!objectsEqual(cleanFilters(values.filters), cleanFilters(router.values.searchParams))) {
                actions.setFilters(searchParams as Filters)
            } else if (!values.propertyDefinitions.results.length) {
                actions.loadPropertyDefinitions()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setFilters: () => {
            const nextValues = cleanFilters(values.filters)
            const urlValues = cleanFilters(router.values.searchParams)
            if (!objectsEqual(nextValues, urlValues)) {
                return [router.values.location.pathname, removeDefaults(nextValues)]
            }
        },
    })),
])
