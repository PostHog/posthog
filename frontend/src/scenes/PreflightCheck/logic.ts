import { kea } from 'kea'
import api from 'lib/api'
import { preflightLogicType } from './logicType'

interface PreflightStatus {
    django?: boolean
    redis?: boolean
    db?: boolean
    initiated?: boolean
    cloud?: boolean
}

export const preflightLogic = kea<preflightLogicType>({
    loaders: {
        preflight: [
            {} as PreflightStatus,
            {
                loadPreflight: async () => (await api.get('_preflight/')) as PreflightStatus,
            },
        ],
    },

    actions: {
        resetPreflight: true,
    },

    reducers: {
        preflight: {
            resetPreflight: () => ({} as PreflightStatus),
        },
    },

    listeners: ({ actions }) => ({
        resetPreflight: async (_, breakpoint) => {
            await breakpoint(1000)
            actions.loadPreflight()
        },
    }),

    events: ({ actions }) => ({
        afterMount: () => {
            actions.loadPreflight()
        },
    }),
})
