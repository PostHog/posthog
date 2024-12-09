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
        setOrderBy: (orderBy: ErrorTrackingQuery['orderBy']) => ({ orderBy }),
        setSelectedIssueIds: (ids: string[]) => ({ ids }),
    }),

    reducers({
        orderBy: [
            'last_seen' as ErrorTrackingQuery['orderBy'],
            { persist: true },
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        selectedIssueIds: [
            [] as string[],
            {
                setSelectedIssueIds: (_, { ids }) => ids,
            },
        ],
    }),

    selectors({
        query: [
            (s) => [
                s.orderBy,
                s.dateRange,
                s.assignee,
                s.filterTestAccounts,
                s.filterGroup,
                s.sparklineSelectedPeriod,
                s.searchQuery,
                s.hasGroupActions,
            ],
            (
                orderBy,
                dateRange,
                assignee,
                filterTestAccounts,
                filterGroup,
                sparklineSelectedPeriod,
                searchQuery,
                hasGroupActions
            ): DataTableNode =>
                errorTrackingQuery({
                    orderBy,
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
        query: () => actions.setSelectedIssueIds([]),
    })),
])
