import { kea } from 'kea'
import { router } from 'kea-router'
import api from 'lib/api'
import { signupLogicType } from 'types/scenes/team/signupLogicType'

export const signupLogic = kea<signupLogicType>({
    loaders: () => ({
        account: [
            [],
            {
                createAccount: async (payload) => {
                    return await api.create('api/organizations/@current/members/', payload)
                },
            },
        ],
    }),

    listeners: {
        createAccountSuccess: ({ account }) => {
            if (account && Object.keys(account).length > 0) router.actions.push('ingestion')
        },
    },
})
