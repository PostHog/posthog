import { kea } from 'kea'
import api from 'lib/api'
import { signupLogicType } from 'types/scenes/team/signupLogicType'

export const signupLogic = kea<signupLogicType>({
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

    listeners: {
        createAccountSuccess: ({ account }) => {
            if (account && Object.keys(account).length > 0) {
                window.location.href = '/ingestion'
            }
        },
    },
})
