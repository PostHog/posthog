import equal from 'fast-deep-equal'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { DataTableNode, ErrorTrackingQuery } from '~/queries/schema/schema-general'

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
            ['dateRange', 'assignee', 'filterTestAccounts', 'filterGroup', 'customSparklineConfig', 'searchQuery'],
        ],
        actions: [
            errorTrackingLogic,
            ['setAssignee', 'setDateRange', 'setFilterGroup', 'setSearchQuery', 'setFilterTestAccounts'],
        ],
    }),

    actions({
        setOrderBy: (orderBy: ErrorTrackingQuery['orderBy']) => ({ orderBy }),
        setStatus: (status: ErrorTrackingQuery['status']) => ({ status }),
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
        status: [
            'active' as ErrorTrackingQuery['status'],
            { persist: true },
            {
                setStatus: (_, { status }) => status,
            },
        ],
        selectedIssueIds: [
            [] as string[],
            {
                setSelectedIssueIds: (_, { ids }) => ids,
            },
        ],
    }),

    selectors(({ values }) => ({
        query: [
            (s) => [s.orderBy, s.status, s.dateRange, s.assignee, s.filterTestAccounts, s.filterGroup, s.searchQuery],
            (orderBy, status, dateRange, assignee, filterTestAccounts, filterGroup, searchQuery): DataTableNode =>
                errorTrackingQuery({
                    orderBy,
                    status,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    // we do not want to recompute the query when then sparkline selection changes
                    // because we have already fetched the alternative option (24h, 30d, custom)
                    customVolume: values.customSparklineConfig,
                    searchQuery,
                    columns: ['error', 'volume', 'occurrences', 'sessions', 'users', 'assignee'],
                }),
        ],
    })),

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
                status: values.status,
                filterTestAccounts: values.filterTestAccounts,
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
            setStatus: () => buildURL(),
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
            if (params.status && !equal(params.status, values.status)) {
                actions.setStatus(params.status)
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
            if (params.searchQuery && !equal(params.searchQuery, values.searchQuery)) {
                actions.setSearchQuery(params.searchQuery)
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
