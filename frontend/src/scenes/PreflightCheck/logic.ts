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
    selectors: {
        socialAuthAvailable: [
            (s) => [s.preflight],
            (preflight: PreflightStatus | null) =>
                preflight && Object.values(preflight.available_social_auth_providers).filter((i) => i).length,
        ],
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
