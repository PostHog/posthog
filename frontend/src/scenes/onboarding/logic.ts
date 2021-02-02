import { kea } from 'kea'
import api from 'lib/api'
import { signupLogicType } from './logicType'

interface AccountResponse {
    redirect_url: string
}

export const signupLogic = kea<signupLogicType<AccountResponse>>({
    loaders: () => ({
        account: [
            null as AccountResponse | null,
            {
                createAccount: async (payload): Promise<AccountResponse> => await api.create('api/signup/', payload),
            },
        ],
    }),

    listeners: {
        createAccountSuccess: ({ account }) => {
            if (account) {
                location.href = account.redirect_url
            }
        },
    },
})
