import { kea } from 'kea'
import { AnyPropertyFilter, EventDefinition } from '~/types'
import { teamLogic } from 'scenes/teamLogic'
import { eventDefinitionsTableLogicType } from './eventDefinitionsTableLogicType'
import api from 'lib/api'
interface EventDefinitionsPaginatedResponse {
    next: string | null
    previous: string | null
    results: EventDefinition[]
}

interface Filters {
    event: string
    properties: AnyPropertyFilter[]
}

export interface EventDefinitionsTableLogicProps {
    key: string
    syncWithUrl?: boolean
}

export const eventDefinitionsTableLogic = kea<
    eventDefinitionsTableLogicType<EventDefinitionsPaginatedResponse, EventDefinitionsTableLogicProps, Filters>
>({
    path: (key) => ['scenes', 'data-management', 'events', 'eventDefinitionsTableLogic', key],
    props: {} as EventDefinitionsTableLogicProps,
    key: (props) => props.key || 'scene',
    actions: {
        loadEventDefinitions: (url: string | null = '') => ({ url }),
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
    loaders: ({}) => ({
        eventDefinitions: [
            { next: null, previous: null, results: [] } as EventDefinitionsPaginatedResponse,
            {
                loadEventDefinitions: async ({ url }, breakpoint) => {
                    if (!url) {
                        url = `api/projects/${teamLogic.values.currentTeamId}/event_definitions/?limit=100`
                    }
                    const results = await api.get(url)
                    breakpoint()
                    return results
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
