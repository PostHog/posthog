import { kea } from 'kea'
import api, { ACTIVITY_PAGE_SIZE, CountedPaginatedResponse } from 'lib/api'
import {
    ActivityLogItem,
    ActivityScope,
    humanize,
    HumanizedActivityLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

import type { activityLogLogicType } from './activityLogLogicType'
import { PaginationManual } from 'lib/components/PaginationControl'
import { urls } from 'scenes/urls'

export const activityLogLogic = kea<activityLogLogicType>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    actions: {
        setPage: (page: number) => ({ page }),
    },
    loaders: ({ values, props }) => ({
        nextPage: [
            { results: [] as ActivityLogItem[], total_count: 0 } as CountedPaginatedResponse,
            {
                fetchNextPage: async () => await api.activity.list(props, values.page),
            },
        ],
        previousPage: [
            { results: [] as ActivityLogItem[], total_count: 0 } as CountedPaginatedResponse,
            {
                fetchPreviousPage: async () => await api.activity.list(props, values.page - 1),
            },
        ],
    }),
    reducers: ({ props }) => ({
        page: [
            1,
            {
                setPage: (_, { page }) => page,
            },
        ],
        humanizedActivity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchNextPageSuccess: (state, { nextPage }) =>
                    nextPage ? humanize(nextPage.results, props.describer) : state,
                fetchPreviousPageSuccess: (state, { previousPage }) =>
                    previousPage ? humanize(previousPage.results, props.describer) : state,
            },
        ],
        totalCount: [
            null as number | null,
            {
                fetchNextPageSuccess: (_, { nextPage }) => nextPage.total_count || null,
                fetchPreviousPageSuccess: (_, { previousPage }) => previousPage.total_count || null,
            },
        ],
    }),
    selectors: ({ actions }) => ({
        pagination: [
            (s) => [s.page, s.totalCount],
            (page, totalCount): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: ACTIVITY_PAGE_SIZE,
                    currentPage: page,
                    entryCount: totalCount || 0,
                    onBackward: actions.fetchPreviousPage,
                    onForward: actions.fetchNextPage,
                }
            },
        ],
    }),
    listeners: ({ actions }) => ({
        setPage: async (_, breakpoint) => {
            await breakpoint()
            actions.fetchNextPage()
        },
    }),
    urlToAction: ({ values, actions, props }) => {
        const onPageChange = (
            searchParams: Record<string, any>,
            hashParams: Record<string, any>,
            pageScope: ActivityScope
        ): void => {
            const pageInURL = searchParams['page']

            const shouldPage =
                (pageScope === ActivityScope.PERSON && hashParams['activeTab'] === 'history') ||
                (pageScope === ActivityScope.FEATURE_FLAG && searchParams['tab'] === 'history') ||
                (pageScope === ActivityScope.INSIGHT && searchParams['tab'] === 'history')

            if (shouldPage && pageInURL && pageInURL !== values.page && pageScope === props.scope) {
                actions.setPage(pageInURL)
            }
        }
        return {
            '/person/*': ({}, searchParams, hashParams) => onPageChange(searchParams, hashParams, ActivityScope.PERSON),
            [urls.featureFlags()]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.FEATURE_FLAG),
            [urls.savedInsights()]: ({}, searchParams, hashParams) =>
                onPageChange(searchParams, hashParams, ActivityScope.INSIGHT),
        }
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchNextPage()
        },
    }),
})
