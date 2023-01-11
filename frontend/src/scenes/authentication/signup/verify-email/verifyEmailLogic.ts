import { actions, kea, listeners, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import type { verifyEmailLogicType } from './verifyEmailLogicType'

export interface ResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}

export interface ValidatedTokenResponseType extends ResponseType {
    token?: string
    uuid?: string
}

export const verifyEmailLogic = kea<verifyEmailLogicType>([
    path(['scenes', 'authentication', 'verifyEmailLogic']),
    actions({
        setView: (view: 'verify' | 'pending' | 'invalid' | null) => ({ view }),
        setUuid: (uuid: string | null) => ({ uuid }),
    }),
    loaders(({}) => ({
        validatedEmailToken: [
            null as ValidatedTokenResponseType | null,
            {
                validateEmailToken: async ({ uuid, token }: { uuid: string; token: string }) => {
                    try {
                        await api.get(`api/verify/${uuid}/?token=${token}`)
                        window.location.href = '/'
                        return { success: true, token, uuid }
                    } catch (e: any) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
    })),
    listeners(({ actions }) => ({
        validateEmailTokenFailure: () => {
            actions.setView('invalid')
        },
    })),
    reducers({
        view: [
            null as 'pending' | 'verify' | 'invalid' | null,
            {
                setView: (_, { view }) => view,
            },
        ],
        uuid: [
            null as string | null,
            {
                setUuid: (_, { uuid }) => uuid,
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/verify_email/:uuid': ({ uuid }) => {
            if (uuid) {
                actions.setUuid(uuid)
                actions.setView('pending')
            }
        },
        '/verify_email/:uuid/:token': ({ uuid, token }) => {
            if (token && uuid) {
                actions.setUuid(uuid)
                actions.setView('verify')
                actions.validateEmailToken({ uuid, token })
            }
        },
        '/verify_email': ({}) => {
            actions.setView('invalid')
        },
    })),
])
