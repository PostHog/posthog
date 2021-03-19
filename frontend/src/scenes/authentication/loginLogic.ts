import { kea } from 'kea'
import api from 'lib/api'
import { loginLogicType } from './loginLogicType'

interface AuthenticateResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export const loginLogic = kea<loginLogicType<AuthenticateResponseType>>({
    actions: {
        setNext: (next: string) => ({ next }),
    },
    reducers: {
        nextUrl: [
            null as string | null,
            {
                setNext: (_, { next }) => next,
            },
        ],
    },
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
    listeners: ({ values }) => ({
        authenticateSuccess: () => {
            if (values.authenticateResponse?.success) {
                window.location.href = values.nextUrl ? values.nextUrl : '/'
            }
        },
    }),
    urlToAction: ({ actions }) => ({
        '/login': (_: any, { next }: { next: string }) => {
            if (next) {
                actions.setNext(next)
            }
        },
    }),
})
