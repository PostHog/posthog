import { actions, afterMount, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'

import { HogQLQuery, NodeKind } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { ErrorTrackingFilters, ErrorTrackingGroup, FilterLogicalOperator } from '~/types'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

const DEFAULT_ERROR_TRACKING_FILTERS: ErrorTrackingFilters = {
    date_from: '-7d',
    date_to: null,
    filter_test_accounts: false,
    filter_group: { type: FilterLogicalOperator.And, values: [] },
    order: 'last_seen',
}

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    actions({
        setFilters: (filters: ErrorTrackingFilters) => ({ filters }),
    }),
    reducers({
        filters: [
            DEFAULT_ERROR_TRACKING_FILTERS,
            {
                setFilters: (_, { filters }) => filters,
            },
        ],
    }),

    loaders(() => ({
        errorGroups: [
            [] as ErrorTrackingGroup[],
            {
                loadErrorGroups: async () => {
                    const query: HogQLQuery = {
                        kind: NodeKind.HogQLQuery,
                        query: hogql`SELECT first_value(properties), count(), count(distinct e.$session_id), count(distinct e.distinct_id)
                                FROM events e
                                WHERE event = '$exception'
                                -- grouping by message for now, will eventually be predefined $exception_group_id
                                GROUP BY e.properties.$exception_type`,
                    }

                    const res = await api.query(query)

                    return res.results.map((r) => {
                        const eventProperties = JSON.parse(r[0])
                        return {
                            id: eventProperties['$exception_type'],
                            title: eventProperties['$exception_type'] || 'Error',
                            description: eventProperties['$exception_message'],
                            occurrences: r[1],
                            uniqueSessions: r[2],
                            uniqueUsers: r[3],
                        }
                    })
                },
            },
        ],
    })),

    listeners(({ actions }) => ({
        setFilters: () => actions.loadErrorGroups(),
    })),

    afterMount(({ actions }) => {
        actions.loadErrorGroups()
    }),
])
