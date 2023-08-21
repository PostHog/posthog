import { kea, path, connect, listeners, actions, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import { forms } from 'kea-forms'
import api from 'lib/api'
import type { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'
import { SSOProvider } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

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

export function handleLoginRedirect(): void {
    let nextURL = '/'
    try {
        const nextPath = router.values.searchParams['next'] || '/'
        const url = new URL(nextPath.startsWith('/') ? location.origin + nextPath : nextPath)
        if (url.protocol === 'http:' || url.protocol === 'https:') {
            nextURL = url.pathname + url.search + url.hash
        }
    } catch (e) {
        // do nothing
    }
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

export const loginLogic = kea<loginLogicType>([
    path(['scenes', 'authentication', 'loginLogic']),
    connect({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
    }),
    actions({
        setGeneralError: (code: string, detail: string) => ({ code, detail }),
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
    loaders(() => ({
        precheckResponse: [
            { status: 'pending' } as PrecheckResponseType,
            {
                precheck: async (
                    {
                        email,
                    }: {
                        email: string
                    },
                    breakpoint
                ) => {
                    if (!email) {
                        return { status: 'pending' }
                    }

                    await breakpoint()
                    const response = await api.create('api/login/precheck', { email })
                    return { status: 'completed', ...response }
                },
            },
        ],
    })),
    forms(({ actions, values }) => ({
        login: {
            defaults: { email: '', password: '' } as LoginForm,
            errors: ({ email, password }) => ({
                email: !email ? 'Please enter your email to continue' : undefined,
                password: !password
                    ? 'Please enter your password to continue'
                    : password.length < 8
                    ? 'Password must be at least 8 characters'
                    : undefined,
            }),
            submit: async ({ email, password }, breakpoint) => {
                await breakpoint()
                try {
                    return await api.create('api/login', { email, password })
                } catch (e) {
                    const { code } = e as Record<string, any>
                    let { detail } = e as Record<string, any>
                    if (code === '2fa_required') {
                        router.actions.push(urls.login2FA())
                        throw e
                    }
                    if (values.featureFlags[FEATURE_FLAGS.REGION_SELECT] && code === 'invalid_credentials') {
                        detail += ' Make sure you have selected the right data region.'
                    }
                    actions.setGeneralError(code, detail)
                    throw e
                }
            },
        },
    })),
    listeners({
        submitLoginSuccess: () => {
            handleLoginRedirect()
            // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
            window.location.reload()
        },
    }),
    urlToAction(({ actions }) => ({
        '/login': (_, { error_code, error_detail, email }) => {
            if (error_code) {
                actions.setGeneralError(error_code, error_detail)
                router.actions.replace('/login', {})
            }

            // This allows us to give a quick login link in the `generate_demo_data` command
            if (email) {
                actions.setLoginValue('email', email)
                actions.precheck({ email })
            }
        },
    })),
])
