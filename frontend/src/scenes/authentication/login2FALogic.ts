import { actions, connect, kea, listeners, path, reducers } from 'kea'
import { forms } from 'kea-forms'
import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { SSOProvider } from '~/types'

import type { login2FALogicType } from './login2FALogicType'
import { handleLoginRedirect } from './loginLogic'

export interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export interface PrecheckResponseType {
    sso_enforcement?: SSOProvider | null
    saml_available: boolean
    status: 'pending' | 'completed'
}

export interface LoginForm {
    email: string
    password: string
}

export interface TwoFactorForm {
    token: string
}

export enum LoginStep {
    LOGIN = 'login',
    TWO_FACTOR = 'two_factor',
}

export const login2FALogic = kea<login2FALogicType>([
    //<login2FALogicType>([
    path(['scenes', 'authentication', 'login2FALogic']),
    connect({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
        setLoginStep: (step: LoginStep) => ({ step }),
        clearGeneralError: true,
    }),
    reducers({
        // This is separate from the login form, so that the form can be submitted even if a general error is present
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
                token: !token
                    ? 'Please enter a token to continue'
                    : token.length !== 6 || isNaN(parseInt(token))
                    ? 'A token must consist of 6 digits'
                    : null,
            }),
            submit: async ({ token }, breakpoint) => {
                breakpoint()
                try {
                    return await api.create('api/login/token', { token })
                } catch (e) {
                    const { code } = e as Record<string, any>
                    const { detail } = e as Record<string, any>
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
