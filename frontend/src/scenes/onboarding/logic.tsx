import React from 'react'
import { kea } from 'kea'
import api from 'lib/api'
import { toast } from 'react-toastify'
import { signupLogicType } from './logicType'

interface AccountResponse {
    redirect_url: string
}

export const signupLogic = kea<signupLogicType<AccountResponse>>({
    loaders: () => ({
        account: [
            null as AccountResponse | null,
            {
                createAccount: async (payload): Promise<AccountResponse> => {
                    try {
                        return await api.create('api/signup/', payload)
                    } catch (response) {
                        toast.error(
                            <div>
                                <h1>Signup failed</h1>
                                <p className="error-details">{response.detail || 'Unknown exception.'}</p>
                            </div>
                        )
                        throw response
                    }
                },
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
