import { kea } from 'kea'
import api from 'lib/api'
import { humanize, HumanizedActivityLogItem } from 'lib/components/ActivityLog/humanizeActivity'
import { activityLogLogicType } from './activityLogLogicType'
import { ActivityLogProps } from 'lib/components/ActivityLog/ActivityLog'

export const activityLogLogic = kea<activityLogLogicType>({
    path: (key) => ['lib', 'components', 'ActivityLog', 'activitylog', 'logic', key],
    props: {} as ActivityLogProps,
    key: ({ scope, id }) => `activity/${scope}/${id || 'all'}`,
    loaders: ({ props }) => ({
        activity: [
            [] as HumanizedActivityLogItem[],
            {
                fetchActivity: async () => {
                    const apiResponse = await api.activity.list(props.scope, props.id)
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
