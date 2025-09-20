import Fuse from 'fuse.js'
import { actions, afterMount, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { QueryEndpointType } from '~/types'

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

export interface QueryEndpointsLogicProps {
    tabId: string
}

export const queryEndpointsLogic = kea<queryEndpointsLogicType>([
    path(['scenes', 'embedded-analytics', 'query-endpoints', 'queryEndpointsLogic']),
    props({} as QueryEndpointsLogicProps),
    key((props) => props.tabId),
    actions({
        setFilters: (filters: Partial<QueryEndpointsFilters>) => ({ filters }),
    }),
    loaders(({ values }) => ({
        queryEndpoints: [
            [] as QueryEndpointType[],
            {
                loadQueryEndpoints: async () => {
                    const response = await api.queryEndpoint.list()

                    let haystack: QueryEndpointType[] = response.results || []

                    if (haystack.length > 0) {
                        const names = haystack.map((endpoint) => endpoint.name)
                        const lastExecutionTimes = await api.queryEndpoint.getLastExecutionTimes(names)

                        haystack = haystack.map((endpoint) => ({
                            ...endpoint,
                            last_executed_at: lastExecutionTimes[endpoint.name],
                        }))
                    }

                    if (values.filters.search) {
                        const fuse = new Fuse<QueryEndpointType>(haystack, {
                            keys: ['name', 'description', 'query.query'],
                            threshold: 0.3,
                        })
                        haystack = fuse.search(values.filters.search).map((result) => result.item)
                    }

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
    selectors({
        isEmpty: [(s) => [s.queryEndpoints], (queryEndpoints) => queryEndpoints.length === 0],
    }),
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
