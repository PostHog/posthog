import { kea } from 'kea'
import api from 'lib/api'
import type { signupLogicType } from './signupLogicType'

export interface AccountResponse {
    success: boolean
    redirect_url?: string
    errorCode?: string
    errorDetail?: string
    errorAttribute?: string
}

export const signupLogic = kea<signupLogicType>({
    path: ['scenes', 'authentication', 'signupLogic'],
    actions: {
        setInitialEmail: (email: string) => ({ email }),
        setFormSubmitted: (submitted: boolean) => ({ submitted }),
    },
    reducers: {
        initialEmail: [
            '',
            {
                setInitialEmail: (_, { email }) => email,
            },
        ],
        // Whether the user has attempted to submit the form; used to trigger validation only after initial submission
        formSubmitted: [
            false,
            {
                setFormSubmitted: (_, { submitted }) => submitted,
            },
        ],
    },
    loaders: () => ({
        signupResponse: [
            null as AccountResponse | null,
            {
                signup: async (payload) => {
                    try {
                        const response = await api.create('api/signup/', payload)
                        return { success: true, ...response }
                    } catch (e: any) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail, errorAttribute: e.attr }
                    }
                },
            },
        ],
    }),
    listeners: () => ({
        signupSuccess: ({ signupResponse }) => {
            if (signupResponse?.success) {
                location.href = signupResponse.redirect_url || '/'
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/signup': ({}, { email }) => {
            if (email) {
                actions.setInitialEmail(email)
            }
        },
    }),
})
