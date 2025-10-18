import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { emailMFAWaitingLogicType } from './emailMFAWaitingLogicType'

export interface ResendEmailResponse {
    success: boolean
}

export const emailMFAWaitingLogic = kea<emailMFAWaitingLogicType>([
    path(['scenes', 'authentication', 'emailMFAWaitingLogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setGeneralError: (code, detail) => ({ code, detail }),
        clearGeneralError: true,
        setResendSuccess: (success) => ({ success }),
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
        resendSuccess: [
            false,
            {
                setResendSuccess: (_, { success }) => success,
            },
        ],
    }),
    loaders(({ actions }) => ({
        resendEmailResponse: [
            null as ResendEmailResponse | null,
            {
                resendEmail: async (_, breakpoint) => {
                    breakpoint()
                    try {
                        const response = await api.create<ResendEmailResponse>('api/login/email-mfa/resend')
                        actions.setResendSuccess(true)
                        return response
                    } catch (e) {
                        const { code, detail } = e as Record<string, any>
                        actions.setGeneralError(code, detail)
                        throw e
                    }
                },
            },
        ],
    })),
    listeners({
        resendEmailSuccess: () => {
            setTimeout(() => {
                // Clear success message after 5 seconds
                // This is intentionally handled in the listener rather than the reducer
            }, 5000)
        },
    }),
])
