import { kea } from 'kea'
import api, { PaginatedResponse } from 'lib/api'
import {
    ActivityLogItem,
    ActivityScope,
    humanize,
    HumanizedActivityLogItem,
} from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogicType } from './activityLogLogicType'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

const urlForScope: { [key in ActivityScope]: (props: ActivityLogProps) => string } = {
    [ActivityScope.FEATURE_FLAG]: ({ id }) => {
        return id
            ? `/api/projects/@current/feature_flags/${id}/activity`
            : `/api/projects/@current/feature_flags/activity`
    },
    [ActivityScope.PERSON]: ({ id }) => {
        return id ? `/api/person/${id}/activity` : `/api/person/activity`
    },
}

export const activityLogLogic = kea<activityLogLogicType>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    loaders: ({ props }) => ({
        activity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchActivity: async () => {
                    const url = urlForScope[props.scope](props)
                    const apiResponse: PaginatedResponse<ActivityLogItem> = await api.get(url)
                    return humanize(apiResponse?.results, props.describer)
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
