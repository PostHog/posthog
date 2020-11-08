import { kea } from 'kea'
import api from 'lib/api'

export const preflightLogic = kea({
    loaders: () => ({
        preflight: [
            {},
            {
                loadPreflight: async () => {
                    return await api.get('_preflight/')
                },
            },
        ],
    }),

    actions: {
        resetPreflight: true,
    },

    reducers: {
        preflight: {
            resetPreflight: () => ({}),
        },
    },

    listeners: ({ actions }) => ({
        resetPreflight: async (_, breakpoint) => {
            await breakpoint(1000)
            actions.loadPreflight()
        },
    }),
})
