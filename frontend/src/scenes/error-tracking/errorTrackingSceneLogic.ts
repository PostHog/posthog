import equal from 'fast-deep-equal'
import { actions, connect, kea, path, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import { objectsEqual } from 'lib/utils'
import { Params } from 'scenes/sceneTypes'

import { DataTableNode, ErrorTrackingQuery } from '~/queries/schema/schema-general'

import { errorTrackingLogic } from './errorTrackingLogic'
import type { errorTrackingSceneLogicType } from './errorTrackingSceneLogicType'
import { errorTrackingQuery } from './queries'
import { defaultSearchParams } from './utils'

export type SparklineSelectedPeriod = 'custom' | 'day'

export const errorTrackingSceneLogic = kea<errorTrackingSceneLogicType>([
    path(['scenes', 'error-tracking', 'errorTrackingSceneLogic']),

    connect(() => ({
        values: [errorTrackingLogic, ['dateRange', 'assignee', 'filterTestAccounts', 'filterGroup', 'searchQuery']],
        actions: [errorTrackingLogic, ['setDateRange', 'setFilterGroup', 'setSearchQuery', 'setFilterTestAccounts']],
    })),

    actions({
        setOrderBy: (orderBy: ErrorTrackingQuery['orderBy']) => ({ orderBy }),
        setOrderDirection: (orderDirection: ErrorTrackingQuery['orderDirection']) => ({ orderDirection }),
        setStatus: (status: ErrorTrackingQuery['status']) => ({ status }),
        setSelectedIssueIds: (ids: string[]) => ({ ids }),
        setSparklineSelectedPeriod: (period: SparklineSelectedPeriod) => ({ period }),
    }),

    reducers({
        orderBy: [
            'last_seen' as ErrorTrackingQuery['orderBy'],
            { persist: true },
            {
                setOrderBy: (_, { orderBy }) => orderBy,
            },
        ],
        orderDirection: [
            'DESC' as ErrorTrackingQuery['orderDirection'],
            { persist: true },
            {
                setOrderDirection: (_, { orderDirection }) => orderDirection,
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
        sparklineSelectedPeriod: [
            'custom' as SparklineSelectedPeriod,
            { persist: true },
            {
                setSparklineSelectedPeriod: (_, { period }) => period,
            },
        ],
        volumeResolution: [20],
    }),

    selectors(({ values }) => ({
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
            ],
            (
                orderBy,
                status,
                dateRange,
                assignee,
                filterTestAccounts,
                filterGroup,
                searchQuery,
                orderDirection
            ): DataTableNode =>
                errorTrackingQuery({
                    orderBy,
                    status,
                    dateRange,
                    assignee,
                    filterTestAccounts,
                    filterGroup,
                    volumeResolution: values.volumeResolution,
                    searchQuery,
                    columns: ['error', 'volume', 'occurrences', 'sessions', 'users'],
                    orderDirection,
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
            const searchParams = defaultSearchParams({
                dateRange: values.dateRange,
                searchQuery: values.searchQuery,
                filterGroup: values.filterGroup,
                filterTestAccounts: values.filterTestAccounts,
            })

            searchParams.status = values.status
            searchParams.orderBy = values.orderBy
            searchParams.orderDirection = values.orderDirection

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
            setOrderDirection: () => buildURL(),
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
            if (params.orderDirection && !equal(params.orderDirection, values.orderDirection)) {
                actions.setOrderDirection(params.orderDirection)
            }
        }
        return {
            '*': urlToAction,
        }
    }),
])
