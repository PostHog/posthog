import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogicType } from './activityLogLogicType'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

export const activityLogLogic = kea<activityLogLogicType>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    loaders: ({ values }) => ({
        activityAPI: [
            { results: [] as ActivityLogItem[] } as PaginatedResponse<ActivityLogItem>,
            {
                fetchActivity: async () => {
                    if (values.nextPageURL === null) {
                        return { results: [], next: null }
                    } else {
                        return await api.get(values.nextPageURL)
                    }
                },
            },
        ],
    }),
    reducers: ({ props }) => ({
        humanizedActivity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchActivitySuccess: (state, { activityAPI }) => [
                    ...state,
                    ...humanize(activityAPI.results, props.describer),
                ],
            },
        ],
        nextPageURL: [
            (props.id
                ? `/api/projects/@current/feature_flags/${props.id}/activity`
                : `/api/projects/@current/feature_flags/activity`) as string | null,
            {
                fetchActivitySuccess: (_, { activityAPI }) => {
                    if (activityAPI.results.length === 10 && activityAPI.next) {
                        // this page was full, and we've got a next page URL, we've not reached the end
                        return activityAPI.next
                    }
                    return null
                },
            },
        ],
    }),
    selectors: {
        hasNextPage: [(s) => [s.nextPageURL], (nextPageURL: string | null) => !!nextPageURL],
    },
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchActivity()
        },
    }),
})
