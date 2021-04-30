import { kea } from 'kea'
import api from 'lib/api'
import { signupLogicType } from './signupLogicType'

interface AccountResponse {
    success: boolean
    redirect_url?: string
    errorCode?: string
    errorDetail?: string
    errorAttribute?: string
}

export const signupLogic = kea<signupLogicType<AccountResponse>>({
    actions: {
        setFormStep: (step: 1 | 2) => ({ step }),
    },
    reducers: {
        formStep: [
            1,
            {
                setFormStep: (_, { step }) => step,
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
                    } catch (e) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail, errorAttribute: e.attr }
                    }
                },
            },
        ],
    }),
    listeners: ({ actions }) => ({
        signupSuccess: ({ signupResponse }) => {
            if (signupResponse?.success) {
                location.href = signupResponse.redirect_url || '/'
            } else {
                if (['email', 'password'].includes(signupResponse?.errorAttribute || '')) {
                    actions.setFormStep(1)
                }
            }
        },
    }),
})
