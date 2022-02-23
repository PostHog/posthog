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
    return router.values.searchParams['next'] || '/'
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
                const redirect = afterLoginRedirect()
                window.location.href = redirect.startsWith('/') ? redirect : '/'
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
