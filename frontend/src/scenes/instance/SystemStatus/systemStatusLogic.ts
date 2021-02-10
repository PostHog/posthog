import api from 'lib/api'
import { kea } from 'kea'
import { systemStatusLogicType } from './systemStatusLogicType'
import { userLogic } from 'scenes/userLogic'
import { SystemStatus } from '~/types'

export const systemStatusLogic = kea<systemStatusLogicType<SystemStatus>>({
    actions: {
        addSystemStatus: (systemStatus: SystemStatus) => ({ systemStatus }),
    },
    loaders: {
        systemStatus: [
            [] as SystemStatus[],
            {
                loadSystemStatus: async () => {
                    const { user } = userLogic.values
                    if (user?.is_multi_tenancy && !user.is_staff) {
                        return []
                    }
                    return (await api.get('_system_status')).results
                },
            },
        ],
    },
    reducers: {
        error: [
            null as null | string,
            {
                loadSystemStatusFailure: (_, { error }) => error,
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSystemStatus()
        },
    }),
})
