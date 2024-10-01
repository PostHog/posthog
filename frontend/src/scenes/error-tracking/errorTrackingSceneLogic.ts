import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { DataTableNode, ErrorTrackingQuery } from '~/queries/schema'

import { errorTrackingLogic } from './errorTrackingLogic'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'
import { errorTrackingQuery } from './queries'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    connect({
        values: [
            errorTrackingLogic,
            [
                'dateRange',
                'assignee',
                'filterTestAccounts',
                'filterGroup',
                'sparklineSelectedPeriod',
                'searchQuery',
                'hasGroupActions',
            ],
        ],
    }),

    actions({
        setOrder: (order: ErrorTrackingQuery['order']) => ({ order }),
        setSelectedRowIndexes: (ids: number[]) => ({ ids }),
    }),
    reducers({
        order: [
            'last_seen' as ErrorTrackingQuery['order'],
            { persist: true },
            {
                setOrder: (_, { order }) => order,
            },
        ],
        selectedRowIndexes: [
            [] as number[],
            {
                setSelectedRowIndexes: (_, { ids }) => ids,
            },
        ],
    }),

    selectors({
        query: [
            (s) => [
                s.order,
                s.dateRange,
                s.assignee,
                s.filterTestAccounts,
                s.filterGroup,
                s.sparklineSelectedPeriod,
                s.searchQuery,
                s.hasGroupActions,
            ],
            (
                order,
                dateRange,
                assignee,
                filterTestAccounts,
                filterGroup,
                sparklineSelectedPeriod,
                searchQuery,
                hasGroupActions
            ): DataTableNode =>
                errorTrackingQuery({
                    order,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    sparklineSelectedPeriod,
                    searchQuery,
                    columns: hasGroupActions
                        ? ['error', 'occurrences', 'sessions', 'users', 'assignee']
                        : ['error', 'occurrences', 'sessions', 'users'],
                }),
        ],
    }),

    subscriptions(({ actions }) => ({
        query: () => actions.setSelectedRowIndexes([]),
    })),
])
