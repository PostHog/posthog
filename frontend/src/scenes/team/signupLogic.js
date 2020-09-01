import { kea } from 'kea'
import api from 'lib/api'

export const signupLogic = kea({
    loaders: () => ({
        account: [
            [],
            {
                createAccount: async (payload) => {
                    return await api.create('api/team/signup/', payload)
                },
            },
        ],
    }),
})
