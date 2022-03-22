import { kea } from 'kea'
import api from 'lib/api'
import { loginLogicType } from './loginLogicType'
import { router } from 'kea-router'

interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
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
    // A safe way to redirect to a new page. Calls history.replaceState() ensuring the URLs origin does not change.
    router.actions.replace(nextURL)
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
            }
        },
    }),
})
