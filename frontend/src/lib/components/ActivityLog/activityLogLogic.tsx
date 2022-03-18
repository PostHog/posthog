import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import { ActivityLogItem, humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogicType } from './activityLogLogicType'

interface ActivityLogLogicProps {
    scope: 'FeatureFlag'
    id?: number
}

export const activityLogLogic = kea<activityLogLogicType<ActivityLogLogicProps>>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogLogicProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    loaders: ({ props }) => ({
        activity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchActivity: async () => {
                    const url = props.id
                        ? `/api/projects/@current/feature_flags/${props.id}/activity`
                        : `/api/projects/@current/feature_flags/activity`
                    const apiResponse: PaginatedResponse<ActivityLogItem> = await api.get(url)
                    return humanize(apiResponse?.results)
                },
            },
        ],
    }),
    events: ({ actions }) => ({
        afterMount: () => {
            actions.fetchActivity()
        },
    }),
})
