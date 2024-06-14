import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import api from 'lib/api'
import { UniversalFiltersGroup } from 'lib/components/UniversalFilters/UniversalFilters'

import { DateRange, ErrorTrackingOrder, HogQLQuery, NodeKind, QuerySchema } from '~/queries/schema'
import { hogql } from '~/queries/utils'
import { ErrorTrackingGroup, FilterLogicalOperator } from '~/types'

import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    actions({
        setDateRange: (dateRange: DateRange) => ({ dateRange }),
        setOrder: (order: ErrorTrackingOrder) => ({ order }),
        setFilterGroup: (filterGroup: UniversalFiltersGroup) => ({ filterGroup }),
        setFilterTestAccounts: (filterTestAccounts: boolean) => ({ filterTestAccounts }),
    }),
    reducers({
        dateRange: [
            { date_from: '-7d', date_to: null } as DateRange,
            {
                setDateRange: (_, { dateRange }) => dateRange,
            },
        ],
        order: [
            'last_seen' as ErrorTrackingOrder,
            {
                setOrder: (_, { order }) => order,
            },
        ],
        filterGroup: [
            { type: FilterLogicalOperator.And, values: [] } as UniversalFiltersGroup,
            {
                setFilterGroup: (_, { filterGroup }) => filterGroup,
            },
        ],
        filterTestAccounts: [
            false as boolean,
            {
                setFilterTestAccounts: (_, { filterTestAccounts }) => filterTestAccounts,
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

    selectors(() => ({
        query: [
            (s) => [s.dateRange, s.order, s.filterGroup, s.filterTestAccounts],
            (dateRange, order, filterGroup, filterTestAccounts): QuerySchema => {
                return {
                    kind: NodeKind.ErrorTrackingGroupsQuery,
                    dateRange: dateRange,
                    order: order,
                    filter_group: filterGroup,
                    filter_test_accounts: filterTestAccounts,
                }
            },
        ],
    })),

    listeners(({ actions }) => ({
        setQuery: () => actions.loadErrorGroups(),
    })),

    afterMount(({ actions }) => {
        actions.loadErrorGroups()
    }),
])
