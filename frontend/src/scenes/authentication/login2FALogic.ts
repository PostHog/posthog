import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import type { login2FALogicType } from './login2FALogicType'
import { handleLoginRedirect } from './loginLogic'

export interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export interface TwoFactorForm {
    token: string
}

export enum LoginStep {
    LOGIN = 'login',
    TWO_FACTOR = 'two_factor',
}

export const login2FALogic = kea<login2FALogicType>([
    path(['scenes', 'authentication', 'login2FALogic']),
    connect(() => ({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        setLoginStep: (step: LoginStep) => ({ step }),
        clearGeneralError: true,
    }),
    reducers({
        generalError: [
            null as { code: string; detail: string } | null,
            {
                setGeneralError: (_, error) => error,
                clearGeneralError: () => null,
            },
        ],
    }),
    forms(({ actions }) => ({
        twofactortoken: {
            defaults: { token: '' } as TwoFactorForm,
            errors: ({ token }) => ({
                token: !token ? 'Please enter a token to continue' : null,
            }),
            submit: async ({ token }, breakpoint) => {
                breakpoint()
                try {
                    return await api.create<any>('api/login/token', { token })
                } catch (e) {
                    const { code, detail } = e as Record<string, any>
                    actions.setGeneralError(code, detail)
                    throw e
                }
            },
        },
    })),
    listeners({
        submitTwofactortokenSuccess: () => {
            handleLoginRedirect()
            // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
            window.location.reload()
        },
    }),
])
