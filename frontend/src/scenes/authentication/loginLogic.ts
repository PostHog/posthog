import { kea } from 'kea'
import api from 'lib/api'
import { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'

interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export function afterLoginRedirect(): string {
    try {
        const nextPath = router.values.searchParams['next'] || '/'
        const url = new URL(nextPath.startsWith('/') ? location.origin + nextPath : nextPath)
        if (url.protocol === 'http:' || url.protocol === 'https:') {
            return url.pathname + url.search + url.hash
        }
    } catch (e) {}
    return '/'
}

export const loginLogic = kea<loginLogicType<AuthenticateResponseType>>({
    path: ['scenes', 'authentication', 'loginLogic'],
    loaders: {
        authenticateResponse: [
            null as AuthenticateResponseType | null,
            {
                authenticate: async ({ email, password }: { email: string; password: string }) => {
                    try {
                        await api.create('api/login', { email, password })
                        return { success: true }
                    } catch (e) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
    },
    listeners: {
        authenticateSuccess: ({ authenticateResponse }) => {
            if (authenticateResponse?.success) {
                window.location.href = afterLoginRedirect()
            }
        },
    },
    urlToAction: ({ actions }) => ({
        '/login': ({}, { error, errorDetail }) => {
            if (error) {
                actions.authenticateSuccess({ success: false, errorCode: error, errorDetail })
            }
        },
    }),
})
