import api from 'lib/api'
import { kea } from 'kea'
import { systemStatusLogicType } from './systemStatusLogicType'
import { userLogic } from 'scenes/userLogic'
import { SystemStatus } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/logic'

export const systemStatusLogic = kea<systemStatusLogicType<SystemStatus>>({
    actions: {
        addSystemStatus: (systemStatus: SystemStatus) => ({ systemStatus }),
    },
    loaders: {
        systemStatus: [
            [] as SystemStatus[],
            {
                loadSystemStatus: async () => {
                    if (preflightLogic.values.preflight?.cloud && !userLogic.values.user?.is_staff) {
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
