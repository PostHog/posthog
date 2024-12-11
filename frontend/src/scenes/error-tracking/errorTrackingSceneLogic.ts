import equal from 'fast-deep-equal'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { DataTableNode, ErrorTrackingQuery } from '~/queries/schema'

import {
    DEFAULT_ERROR_TRACKING_DATE_RANGE,
    DEFAULT_ERROR_TRACKING_FILTER_GROUP,
    errorTrackingLogic,
} from './errorTrackingLogic'
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
        actions: [
            errorTrackingLogic,
            ['setAssignee', 'setDateRange', 'setFilterGroup', 'setSearchQuery', 'setFilterTestAccounts'],
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

    actionToUrl(({ values }) => {
        const buildURL = (): [
            string,
            Params,
            Record<string, any>,
            {
                replace: boolean
            }
        ] => {
            const searchParams: Params = {
                orderBy: values.orderBy,
                filterTestAccounts: values.filterTestAccounts,
            }

            if (values.assignee) {
                searchParams.assignee = values.assignee
            }
            if (values.searchQuery) {
                searchParams.searchQuery = values.searchQuery
            }
            if (!objectsEqual(values.filterGroup, DEFAULT_ERROR_TRACKING_FILTER_GROUP)) {
                searchParams.filterGroup = values.filterGroup
            }
            if (!objectsEqual(values.dateRange, DEFAULT_ERROR_TRACKING_DATE_RANGE)) {
                searchParams.dateRange = values.dateRange
            }

            if (!objectsEqual(searchParams, router.values.searchParams)) {
                return [router.values.location.pathname, searchParams, router.values.hashParams, { replace: true }]
            }

            return [
                router.values.location.pathname,
                router.values.searchParams,
                router.values.hashParams,
                { replace: false },
            ]
        }

        return {
            setOrderBy: () => buildURL(),
            setAssignee: () => buildURL(),
            setDateRange: () => buildURL(),
            setFilterGroup: () => buildURL(),
            setSearchQuery: () => buildURL(),
            setFilterTestAccounts: () => buildURL(),
        }
    }),

    urlToAction(({ actions, values }) => {
        const urlToAction = (_: any, params: Params): void => {
            if (params.orderBy && !equal(params.orderBy, values.orderBy)) {
                actions.setOrderBy(params.orderBy)
            }
            if (params.dateRange && !equal(params.dateRange, values.dateRange)) {
                actions.setDateRange(params.dateRange)
            }
            if (params.filterGroup && !equal(params.filterGroup, values.filterGroup)) {
                actions.setFilterGroup(params.filterGroup)
            }
            if (params.filterTestAccounts && !equal(params.filterTestAccounts, values.filterTestAccounts)) {
                actions.setFilterTestAccounts(params.filterTestAccounts)
            }
            if (params.assignee && !equal(params.assignee, values.assignee)) {
                actions.setAssignee(params.assignee)
            }
            if (params.searchQuery && !equal(params.searchQuery, values.searchQuery)) {
                actions.setSearchQuery(params.searchQuery)
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
