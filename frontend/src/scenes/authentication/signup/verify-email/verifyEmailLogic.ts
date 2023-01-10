import { kea, path, reducers } from 'kea'
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
    path(['scenes', 'authentication', 'passwordResetLogic']),
    loaders(({}) => ({
        validatedEmailToken: [
            null as ValidatedTokenResponseType | null,
            {
                validateEmailToken: async ({ uuid, token }: { uuid: string; token: string }) => {
                    try {
                        await api.get(`api/reset/${uuid}/?token=${token}`)
                        return { success: true, token, uuid }
                    } catch (e: any) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
    })),
    reducers({}),
    urlToAction(({ actions }) => ({
        '/verify_email/:uuid/:token': ({ uuid, token }) => {
            if (token && uuid) {
                actions.validateEmailToken({ uuid, token })
            }
        },
    })),
])
