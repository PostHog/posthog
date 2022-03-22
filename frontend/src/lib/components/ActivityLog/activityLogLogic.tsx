import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

import type { activityLogLogicType } from './activityLogLogicType'
import { PaginationManual } from 'lib/components/PaginationControl'

interface CountedPaginatedResponse extends PaginatedResponse<ActivityLogItem> {
    total_count: number
}

export const activityLogLogic = kea<activityLogLogicType<CountedPaginatedResponse>>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    loaders: ({ values }) => ({
        nextPage: [
            { results: [] as ActivityLogItem[], total_count: 0 } as CountedPaginatedResponse,
            {
                fetchNextPage: async () => {
                    const url = values.nextPageURL
                    if (url === null) {
                        return null
                    } else {
                        return await api.get(url)
                    }
                },
            },
        ],
        previousPage: [
            { results: [] as ActivityLogItem[], total_count: 0 } as CountedPaginatedResponse,
            {
                fetchPreviousPage: async () => {
                    const url = values.previousPageURL
                    if (url === null) {
                        return null
                    } else {
                        return await api.get(url)
                    }
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        page: [
            props.startingPage ? props.startingPage - 1 : 0,
            {
                fetchNextPageSuccess: (state) => state + 1,
                fetchPreviousPageSuccess: (state) => state - 1,
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
        previousPageURL: [
            null as string | null,
            {
                fetchNextPageSuccess: (_, { nextPage }) => nextPage.previous || null,
                fetchPreviousPageSuccess: (_, { previousPage }) => previousPage.previous || null,
            },
        ],
        totalCount: [
            null as number | null,
            {
                fetchNextPageSuccess: (_, { nextPage }) => nextPage.total_count || null,
                fetchPreviousPageSuccess: (_, { previousPage }) => previousPage.total_count || null,
            },
        ],
        nextPageURL: [
            (props.id
                ? `/api/projects/@current/feature_flags/${props.id}/activity?page=${props.startingPage || 1}`
                : `/api/projects/@current/feature_flags/activity?page=${props.startingPage || 1}`) as string | null,
            {
                fetchNextPageSuccess: (_, { nextPage }) => nextPage.next || null,
                fetchPreviousPageSuccess: (_, { previousPage }) => previousPage.next || null,
            },
        ],
    }),
    selectors: ({ actions }) => ({
        hasNextPage: [(s) => [s.nextPageURL], (nextPageURL: string | null) => !!nextPageURL],
        hasPreviousPage: [(s) => [s.previousPageURL], (previousPageURL: string | null) => !!previousPageURL],
        pagination: [
            (s) => [s.page, s.totalCount],
            (page, totalCount): PaginationManual => {
                return {
                    controlled: true,
                    pageSize: 10,
                    currentPage: page,
                    entryCount: totalCount || 0,
                    onBackward: () => actions.fetchPreviousPage(),
                    onForward: () => actions.fetchNextPage(),
                }
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchNextPage()
        },
    }),
})
