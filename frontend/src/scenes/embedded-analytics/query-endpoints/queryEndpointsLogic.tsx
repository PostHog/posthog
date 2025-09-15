import Fuse from 'fuse.js'
import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import { AccessControlLevel, QueryEndpointType } from '~/types'

import type { queryEndpointsLogicType } from './queryEndpointsLogicType'

export interface QueryEndpointsFilters {
    search: string
    createdBy: string
}

export const DEFAULT_FILTERS: QueryEndpointsFilters = {
    search: '',
    createdBy: 'All users',
}

export type QueryEndpointsFuse = Fuse<QueryEndpointType>

export const queryEndpointsLogic = kea<queryEndpointsLogicType>([
    path(['scenes', 'embedded-analytics', 'query-endpoints', 'queryEndpointsLogic']),
    actions({
        setFilters: (filters: Partial<QueryEndpointsFilters>) => {
            return { filters }
        },
    }),
    loaders(({ values }) => ({
        queryEndpoints: [
            [] as QueryEndpointType[],
            {
                loadQueryEndpoints: async () => {
                    let haystack: QueryEndpointType[] = [
                        {
                            id: 1,
                            name: 'Query Endpoint 1',
                            description: 'First query endpoint for testing',
                            created_at: '2021-01-01',
                            created_by: {
                                id: 1,
                                first_name: 'Jovan',
                                last_name: '',
                                email: 'jovan+dev@posthog.com',
                                uuid: '00000000-0000-0000-0000-000000000000',
                                distinct_id: '123',
                            },
                            url: 'https://query-endpoint-1.example.com',
                            sql: 'SELECT * FROM events WHERE event = \'$pageview\' LIMIT 100',
                            user_access_level: AccessControlLevel.Editor,
                        },
                        {
                            id: 2,
                            name: 'Query Endpoint 2',
                            description: 'Second query endpoint for analytics',
                            created_at: '2021-01-02',
                            created_by: {
                                id: 2,
                                first_name: 'Jovan',
                                last_name: '',
                                email: 'jovan+dev@posthog.com',
                                uuid: '00000000-0000-0000-0000-000000000000',
                                distinct_id: '123',
                            },
                            url: 'https://query-endpoint-2.example.com',
                            sql: 'SELECT person_id, count() as event_count FROM events GROUP BY person_id ORDER BY event_count DESC',
                            user_access_level: AccessControlLevel.Editor,
                        },
                    ]

                    // Apply search filter
                    if (values.filters.search) {
                        const fuse = new Fuse<QueryEndpointType>(haystack, {
                            keys: ['name', 'description', 'sql'],
                            threshold: 0.7,
                        })
                        haystack = fuse.search(values.filters.search).map((result) => result.item)
                    }

                    // Apply createdBy filter
                    if (values.filters.createdBy !== 'All users') {
                        haystack = haystack.filter(
                            (endpoint) =>
                                endpoint.created_by &&
                                `${endpoint.created_by.first_name} ${endpoint.created_by.last_name}`.trim() ===
                                    values.filters.createdBy
                        )
                    }

                    return haystack
                },
            },
        ],
    })),
    reducers({
        filters: [
            DEFAULT_FILTERS as QueryEndpointsFilters,
            {
                setFilters: (state, { filters }) => ({ ...state, ...filters }),
            },
        ],
    }),
    listeners(({ actions }) => ({
        setFilters: () => {
            actions.loadQueryEndpoints()
        },
    })),
    afterMount(({ actions }) => {
        actions.loadQueryEndpoints()
    }),
])
