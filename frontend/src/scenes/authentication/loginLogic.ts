import { kea, path, connect, listeners } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import { forms } from 'kea-forms'
import api from 'lib/api'
import type { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'
import { SSOProviders } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

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

export const loginLogic = kea<loginLogicType>([
    path(['scenes', 'authentication', 'loginLogic']),
    connect({
        values: [preflightLogic, ['preflight'], featureFlagLogic, ['featureFlags']],
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
                    if (values.featureFlags[FEATURE_FLAGS.REGION_SELECT] && code === 'invalid_credentials') {
                        detail = 'Invalid email or password. Make sure you have selected the right data region.'
                    }
                    actions.setLoginManualErrors({
                        generic: {
                            code,
                            detail,
                        },
                    })
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
        '/login': ({}, { error_code, error_detail }) => {
            if (error_code) {
                actions.setLoginManualErrors({ generic: { code: error_code, detail: error_detail } })
                router.actions.replace('/login', {})
            }
        },
    })),
])
