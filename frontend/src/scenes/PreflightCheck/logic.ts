import { kea } from 'kea'
import api from 'lib/api'
import { PreflightStatus } from '~/types'
import { preflightLogicType } from './logicType'

export const preflightLogic = kea<preflightLogicType<PreflightStatus>>({
    loaders: {
        preflight: [
            null as PreflightStatus | null,
            {
                loadPreflight: async () => await api.get('_preflight/'),
            },
        ],
    },
    actions: {
        resetPreflight: true,
    },
    reducers: {
        preflight: {
            resetPreflight: () => null,
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
