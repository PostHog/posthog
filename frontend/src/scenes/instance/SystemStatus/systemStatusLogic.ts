import api from 'lib/api'
import { kea } from 'kea'
import { systemStatusLogicType } from 'types/scenes/system_status/systemStatusLogicType'

interface SystemStatus {
    metric: string
    value: string
}

export const systemStatusLogic = kea<systemStatusLogicType<SystemStatus>>({
    actions: {
        addSystemStatus: (systemStatus: SystemStatus) => ({ systemStatus }),
    },
    loaders: {
        systemStatus: [
            [] as SystemStatus[],
            {
                loadSystemStatus: async () => {
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
