import api from 'lib/api'
import { kea } from 'kea'

interface Error {
    detail: string
    code: string
}

interface SystemStatus {
    metric: string
    value: string
}

export const systemStatusLogic = kea({
    actions: {
        setError: (error: Error) => ({ error }),
        addSystemStatus: (systemStatus: SystemStatus) => ({ systemStatus }),
    },
    loaders: {
        systemStatus: [
            [],
            {
                loadSystemStatus: async () => {
                    return (await api.get('_system_status')).results
                },
            },
        ],
    },
    reducers: {
        systemStatus: {
            addSystemStatus: (state: Array<SystemStatus>, { systemStatus }) => [systemStatus, ...state],
        },
        error: [
            false,
            {
                setError: (_, { error }) => error,
            },
        ],
    },

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadSystemStatus()
        },
    }),
})
