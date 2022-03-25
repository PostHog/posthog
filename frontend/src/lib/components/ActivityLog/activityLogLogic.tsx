import { kea } from 'kea'
import api, { ACTIVITY_PAGE_SIZE, CountedPaginatedResponse } from 'lib/api'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
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
                fetchNextPage: async () => {
                    return await api.activity.list(props, values.page)
                },
            },
        ],
        previousPage: [
            { results: [] as ActivityLogItem[], total_count: 0 } as CountedPaginatedResponse,
            {
                fetchPreviousPage: async () => {
                    return await api.activity.list(props, values.page - 1)
                },
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
    listeners: ({ actions }) => ({ setPage: actions.fetchNextPage }),
    urlToAction: ({ values, actions }) => {
        const onPageChange = (searchParams: Record<string, any>): void => {
            const pageInURL = searchParams['page']
            if (pageInURL && pageInURL !== values.page) {
                actions.setPage(pageInURL)
            }
        }
        return {
            '/person/*': ({}, searchParams) => onPageChange(searchParams),
            [urls.featureFlags()]: ({}, searchParams) => onPageChange(searchParams),
        }
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchNextPage()
        },
    }),
})
