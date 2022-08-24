import { kea } from 'kea'
import api from 'lib/api'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import type { signupLogicType } from './signupLogicType'

export interface AccountResponse {
    success: boolean
    redirect_url?: string
    errorCode?: string
    errorDetail?: string
    errorAttribute?: string
}

export const signupLogic = kea<signupLogicType>({
    connect: {
        values: [preflightLogic, ['preflight']],
    },
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
    urlToAction: ({ actions, values }) => ({
        '/signup': ({}, { email }) => {
            if (email) {
                if (values.preflight?.demo) {
                    // In demo mode no password is needed, so we can log in right away
                    // This allows us to give a quick login link in the `generate_demo_data` command
                    // X and Y are placeholders, irrelevant because the account should already exists
                    actions.signup({ email, first_name: 'X', organization_name: 'Y' })
                } else {
                    actions.setInitialEmail(email)
                }
            }
        },
    }),
})
