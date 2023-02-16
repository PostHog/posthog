import { kea, path, connect, afterMount, listeners, actions, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { forms } from 'kea-forms'
import api from 'lib/api'
import type { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'
import { SSOProviders } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { lemonToast } from '@posthog/lemon-ui'

export interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export interface PrecheckResponseType {
    sso_enforcement?: SSOProviders | null
    saml_available: boolean
    status: 'pending' | 'completed'
}

export function handleLoginRedirect(): void {
    let nextURL = '/'
    try {
        const nextPath = router.values.searchParams['next'] || '/'
        const url = new URL(nextPath.startsWith('/') ? location.origin + nextPath : nextPath)
        if (url.protocol === 'http:' || url.protocol === 'https:') {
            nextURL = url.pathname + url.search + url.hash
        }
    } catch (e) {}
    // A safe way to redirect to a user input URL. Calls history.replaceState() ensuring the URLs origin does not change.
    router.actions.replace(nextURL)
}

export interface LoginForm {
    email: string
    password: string
}

export interface TwoFactorForm {
    token: number | null
}

export enum LoginStep {
    LOGIN = 'login',
    TWO_FACTOR = 'two_factor',
}

export const setup2FALogic = kea<loginLogicType>([
    path(['scenes', 'authentication', 'loginLogic']),
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
        loginStep: [
            LoginStep.LOGIN,
            {
                setLoginStep: (_, { step }) => step,
            },
        ],
    }),
    loaders(() => ({
        startSetup: [
            { status: 'pending' } as PrecheckResponseType,
            {
                setup: async (_, breakpoint) => {
                    await breakpoint()
                    await api.get('api/users/@me/start_2fa_setup/')
                    return { status: 'completed' }
                },
            },
        ],
    })),
    forms(({ actions }) => ({
        token: {
            defaults: { token: null } as TwoFactorForm,
            errors: ({ token }) => ({
                token: !token ? 'Please enter a token to continued' : undefined,
            }),
            submit: async ({ token }, breakpoint) => {
                await breakpoint()
                try {
                    return await api.create('api/users/@me/validate_2fa/', { token })
                } catch (e) {
                    const { code } = e as Record<string, any>
                    const { detail } = e as Record<string, any>
                    actions.setGeneralError(code, detail)
                    throw e
                }
            },
        },
    })),

    afterMount(({ actions }) => actions.setup()),
    listeners(({ props }) => ({
        submitTokenSuccess: () => {
            lemonToast.success('2FA method added successfully')
            props.onSuccess && props.onSuccess()
        },
    })),
])
