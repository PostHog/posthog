import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

import type { activityLogLogicType } from './activityLogLogicType'

export const activityLogLogic = kea<activityLogLogicType>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    loaders: ({ values }) => ({
        nextPage: [
            { results: [] as ActivityLogItem[], current_page: 1 } as PaginatedResponse<ActivityLogItem>,
            {
                fetchNextPage: async () => {
                    const url = values.nextPageURL
                    if (url === null) {
                        return { results: [], next: null, previous: null }
                    } else {
                        return await api.get(url)
                    }
                },
            },
        ],
        previousPage: [
            { results: [] as ActivityLogItem[], current_page: 1 } as PaginatedResponse<ActivityLogItem>,
            {
                fetchPreviousPage: async () => {
                    const url = values.previousPageURL
                    if (url === null) {
                        return { results: [], next: null, previous: null }
                    } else {
                        return await api.get(url)
                    }
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        page: [
            props.startingPage || 1,
            {
                fetchNextPageSuccess: (state) => state + 1,
                fetchPreviousPageSuccess: (state) => state - 1,
            },
        ],
        humanizedActivity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchNextPageSuccess: (_, { nextPage }) => humanize(nextPage.results, props.describer),
                fetchPreviousPageSuccess: (_, { previousPage }) => humanize(previousPage.results, props.describer),
            },
        ],
        previousPageURL: [
            null as string | null,
            {
                fetchNextPageSuccess: (_, { nextPage }) => nextPage.previous || null,
                fetchPreviousPageSuccess: (_, { previousPage }) => previousPage.previous || null,
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
    selectors: {
        hasNextPage: [(s) => [s.nextPageURL], (nextPageURL: string | null) => !!nextPageURL],
        hasPreviousPage: [(s) => [s.previousPageURL], (previousPageURL: string | null) => !!previousPageURL],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchNextPage()
        },
    }),
})
