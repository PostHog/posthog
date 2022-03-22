import { kea } from 'kea'
import api from 'lib/api'
import { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'
import { SSOProviders } from '~/types'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

interface PrecheckResponseType {
    sso_enforcement?: SSOProviders | null
    status: 'pending' | 'completed'
}

export function afterLoginRedirect(): string {
    try {
        const nextPath = router.values.searchParams['next'] || '/'
        const url = new URL(nextPath.startsWith('/') ? location.origin + nextPath : nextPath)
        if (url.protocol === 'http:' || url.protocol === 'https:') {
            return location.origin + url.pathname + url.search + url.hash
        }
    } catch (e) {}
    return location.origin
}

export const loginLogic = kea<loginLogicType<AuthenticateResponseType, PrecheckResponseType>>({
    path: ['scenes', 'authentication', 'loginLogic'],
    connect: {
        values: [preflightLogic, ['preflight']],
    },
    loaders: ({ values }) => ({
        precheckResponse: [
            { status: 'pending' } as PrecheckResponseType,
            {
                precheck: async ({ email }: { email: string }) => {
                    if (!values.shouldPrecheckResponse) {
                        return { status: 'completed' }
                    }

                    if (!email) {
                        return { status: 'pending' }
                    }

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
                window.location.href = afterLoginRedirect()
            }
        },
    },
    selectors: {
        shouldPrecheckResponse: [(s) => [s.preflight], (preflight): boolean => !!preflight?.cloud],
    },
    urlToAction: ({ actions }) => ({
        '/login': ({}, { error_code, error_detail }) => {
            if (error_code) {
                actions.authenticateSuccess({ success: false, errorCode: error_code, errorDetail: error_detail })
            }
        },
    }),
})
