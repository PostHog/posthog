import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { subscriptions } from 'kea-subscriptions'

import { DataTableNode } from '~/queries/schema/schema-general'

import { errorFiltersLogic } from './components/ErrorFilters/errorFiltersLogic'
import { issueActionsLogic } from './components/IssueActions/issueActionsLogic'
import { issueQueryOptionsLogic } from './components/IssueQueryOptions/issueQueryOptionsLogic'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'
import { errorTrackingQuery } from './queries'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    connect(() => ({
        values: [
            errorFiltersLogic,
            ['dateRange', 'filterTestAccounts', 'filterGroup', 'searchQuery'],
            issueQueryOptionsLogic,
            ['assignee', 'orderBy', 'orderDirection', 'status', 'volumeResolution'],
        ],
        actions: [issueActionsLogic, ['mutationSuccess', 'mutationFailure']],
    })),

    actions({
        setSelectedIssueIds: (ids: string[]) => ({ ids }),
    }),

    reducers({
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
                s.status,
                s.dateRange,
                s.assignee,
                s.filterTestAccounts,
                s.filterGroup,
                s.searchQuery,
                s.orderDirection,
                s.volumeResolution,
            ],
            (
                orderBy,
                status,
                dateRange,
                assignee,
                filterTestAccounts,
                filterGroup,
                searchQuery,
                orderDirection,
                volumeResolution
            ): DataTableNode =>
                errorTrackingQuery({
                    orderBy,
                    status,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    volumeResolution,
                    searchQuery,
                    columns: ['error', 'volume', 'occurrences', 'sessions', 'users'],
                    orderDirection,
                }),
        ],
    }),

    subscriptions(({ actions }) => ({
        query: () => actions.setSelectedIssueIds([]),
    })),

    listeners(({ actions }) => ({
        mutationSuccess: () => actions.setSelectedIssueIds([]),
        mutationFailure: () => actions.setSelectedIssueIds([]),
    })),
])
