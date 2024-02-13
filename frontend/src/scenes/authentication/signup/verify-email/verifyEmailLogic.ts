import { actions, kea, path, reducers } from 'kea'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

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
        setView: (view: 'verify' | 'pending' | 'invalid' | 'success' | null) => ({ view }),
        setUuid: (uuid: string | null) => ({ uuid }),
        requestVerificationLink: (uuid: string) => ({ uuid }),
        validateEmailTokenSuccess: (response: ValidatedTokenResponseType) => ({ response }),
    }),
    loaders(({ actions }) => ({
        validatedEmailToken: [
            null as ValidatedTokenResponseType | null,
            {
                validateEmailToken: async ({ uuid, token }: { uuid: string; token: string }, breakpoint) => {
                    try {
                        await api.create(`api/users/${uuid}/verify_email/`, { token, uuid })
                        actions.setView('success')
                        await breakpoint(2000)
                        window.location.href = '/'
                        return { success: true, token, uuid }
                    } catch (e: any) {
                        actions.setView('invalid')
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
        newlyRequestedVerificationLink: [
            null as boolean | null,
            {
                requestVerificationLink: async ({ uuid }: { uuid: string }) => {
                    try {
                        await api.create(`api/users/${uuid}/request_email_verification/`, { uuid })
                        lemonToast.success(
                            'A new verification link has been sent to the associated email address. Please check your inbox.'
                        )
                        return true
                    } catch (e: any) {
                        if (e.code === 'throttled') {
                            lemonToast.error(
                                'You have requested a new verification link too many times. Please try again later.'
                            )
                            return false
                        }
                        lemonToast.error(
                            'Requesting verification link failed. Please try again later or contact support.'
                        )
                        return false
                    }
                },
            },
        ],
    })),
    reducers({
        view: [
            null as 'pending' | 'verify' | 'invalid' | 'success' | null,
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
        '/verify_email': () => {
            actions.setView('invalid')
        },
    })),
])
