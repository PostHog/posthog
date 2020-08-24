import { kea } from 'kea'
import api from 'lib/api'

export const preflightLogic = kea({
    loaders: () => ({
        preflight: [
            [],
            {
                loadPreflight: async () => {
                    return await api.get('_preflight/')
                },
            },
        ],
    }),
})
