import { kea } from 'kea'
import api from 'lib/api'

export const teamLogic = kea({
    loaders: () => ({
        users: {
            __default: {},
            loadUsers: async () => {
                return await api.get('api/team/user/')
            },
        },
    }),
    events: ({ actions }) => ({
        afterMount: actions.loadUsers,
    }),
})
