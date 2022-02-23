import { kea } from 'kea'
import { AnyPropertyFilter, EventDefinition, PropertyDefinition } from '~/types'
import { eventDefinitionsTableLogicType } from './eventDefinitionsTableLogicType'
import api from 'lib/api'

import { isPostHogProp } from 'lib/components/PropertyKeyInfo'
import { toParams } from 'lib/utils'
import { encodeParams } from 'kea-router'
interface DefinitionsPaginatedResponse {
    count: number
    next: string | null
    previous: string | null
}

interface EventDefinitionsPaginatedResponse extends DefinitionsPaginatedResponse {
    results: EventDefinition[]
}

export interface PropertyDefinitionWithExample extends PropertyDefinition {
    example?: string
}

interface PropertyDefinitionsPaginatedResponse extends DefinitionsPaginatedResponse {
    results: PropertyDefinitionWithExample[]
}

interface Filters {
    event: string
    properties: AnyPropertyFilter[]
}

export const EVENT_DEFINITIONS_PER_PAGE = 100
export const PROPERTY_DEFINITIONS_PER_EVENT = 5

export interface EventDefinitionsTableLogicProps {
    key: string
    syncWithUrl?: boolean
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
        loadEventDefinitions: (url: string | null = '') => ({ url }),
        loadPropertiesForEvent: (definition: EventDefinition) => ({ definition }),
        setFilters: (filters: Filters) => ({ filters }),
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
    },
    loaders: ({ values }) => ({
        eventDefinitions: [
            { count: 0, next: null, previous: null, results: [] } as EventDefinitionsPaginatedResponse,
            {
                loadEventDefinitions: async ({ url }, breakpoint) => {
                    if (!url) {
                        url = `api/projects/@current/event_definitions/?limit=${EVENT_DEFINITIONS_PER_PAGE}`
                    }
                    const results = await api.get(url)
                    breakpoint()
                    return results
                },
            },
        ],
        eventPropertiesCacheMap: [
            {} as Record<string, PropertyDefinitionsPaginatedResponse>,
            {
                loadPropertiesForEvent: async ({ definition }) => {
                    if (definition.id in values.eventPropertiesCacheMap) {
                        return values.eventPropertiesCacheMap
                    }
                    let response = await api.get(
                        `api/projects/@current/property_definitions/?${encodeParams({
                            event_names: [definition.name],
                            is_event_property: true,
                        })}`
                    )
                    // Fetch one event to populate properties with examples
                    const exampleEventProperties = (
                        await api.get(
                            `api/projects/@current/events/?${toParams({
                                event: definition.name,
                                orderBy: ['-timestamp'],
                                limit: 1,
                            })}`
                        )
                    )?.results?.[0].properties
                    // Exclude showing PH properties
                    const nonPostHogProperties: PropertyDefinitionWithExample[] = response.results
                        .filter((property: PropertyDefinition) => !isPostHogProp(property.name))
                        .map((property: PropertyDefinition) => ({
                            ...property,
                            example: exampleEventProperties?.[property.name]?.toString(),
                        }))
                    response = {
                        ...response,
                        count: nonPostHogProperties.length,
                        results: nonPostHogProperties,
                    }

                    return {
                        ...values.eventPropertiesCacheMap,
                        [definition.id]: response,
                    }
                },
            },
        ],
    }),
    urlToAction: ({ actions, values, props }) => ({
        '/events/stats': ({}, searchParams) => {
            if (props.syncWithUrl) {
                actions.setFilters(searchParams as Filters)
                if (!values.eventDefinitions.results.length && !values.eventDefinitionsLoading) {
                    actions.loadEventDefinitions()
                }
            }
        },
    }),
    events: ({ actions, values }) => ({
        afterMount: () => {
            if (!values.eventDefinitions.results.length && !values.eventDefinitionsLoading) {
                actions.loadEventDefinitions()
            }
        },
    }),
})
