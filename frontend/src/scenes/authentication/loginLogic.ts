import { kea } from 'kea'
import api from 'lib/api'
import type { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'
import { SSOProviders } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

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

export const loginLogic = kea<loginLogicType>({
    path: ['scenes', 'authentication', 'loginLogic'],
    connect: {
        values: [preflightLogic, ['preflight']],
    },
    loaders: () => ({
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
        authenticateResponse: [
            null as AuthenticateResponseType | null,
            {
                authenticate: async ({ email, password }: { email: string; password: string }) => {
                    try {
                        await api.create('api/login', { email, password })
                        return { success: true }
                    } catch (e) {
                        return {
                            success: false,
                            errorCode: (e as Record<string, any>).code,
                            errorDetail: (e as Record<string, any>).detail,
                        }
                    }
                },
            },
        ],
    }),
    listeners: {
        authenticateSuccess: ({ authenticateResponse }) => {
            if (authenticateResponse?.success) {
                handleLoginRedirect()
                // Reload the page after login to ensure POSTHOG_APP_CONTEXT is set correctly.
                window.location.reload()
            }
        },
    },
    urlToAction: ({ actions }) => ({
        '/login': ({}, { error_code, error_detail }) => {
            if (error_code) {
                actions.authenticateSuccess({ success: false, errorCode: error_code, errorDetail: error_detail })
                router.actions.replace('/login', {})
            }
        },
    }),
})
