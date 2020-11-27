import { kea } from 'kea'
import api from 'lib/api'
import { signupLogicType } from 'types/scenes/Signup/logicType'

export const signupLogic = kea<signupLogicType>({
    loaders: () => ({
        account: [
            [],
            {
                createAccount: async (payload) => await api.create('api/signup/', payload),
            },
        ],
    }),

    listeners: {
        createAccountSuccess: ({ account }) => {
            if (account) {
                location.href = '/ingestion'
            }
        },
    },
})
