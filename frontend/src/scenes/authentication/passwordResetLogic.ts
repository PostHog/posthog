import { kea } from 'kea'
import api from 'lib/api'
import { successToast } from 'lib/utils'

import { passwordResetLogicType } from './passwordResetLogicType'
interface ResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}
interface ResetResponseType extends ResponseType {
    email?: string
}

interface ValidatedTokenResponseType extends ResponseType {
    token?: string
    uuid?: string
}

export const passwordResetLogic = kea<
    passwordResetLogicType<ResetResponseType, ResponseType, ValidatedTokenResponseType>
>({
    loaders: ({ values }) => ({
        resetResponse: [
            null as ResetResponseType | null,
            {
                reset: async ({ email }: { email: string }) => {
                    try {
                        await api.create('api/reset/', { email })
                        return { success: true, email }
                    } catch (e) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
        validatedResetToken: [
            null as ValidatedTokenResponseType | null,
            {
                validateResetToken: async ({ uuid, token }: { uuid: string; token: string }) => {
                    try {
                        await api.get(`api/reset/${uuid}/?token=${token}`)
                        return { success: true, token, uuid }
                    } catch (e) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
        newPasswordResponse: [
            null as ResponseType | null,
            {
                updatePassword: async ({
                    password,
                    passwordConfirm,
                }: {
                    password: string
                    passwordConfirm: string
                }) => {
                    if (!values.validatedResetToken?.token || !values.validatedResetToken.uuid) {
                        return {
                            success: false,
                            errorCode: 'invalid_token',
                            errorDetail: 'Your link is invalid or expired.',
                        }
                    }
                    if (passwordConfirm !== password) {
                        return {
                            success: false,
                            errorCode: 'confirmation_does_not_match',
                            errorDetail: 'Password confirmation does not match.',
                        }
                    }
                    try {
                        await api.create(`api/reset/${values.validatedResetToken.uuid}/`, {
                            password,
                            token: values.validatedResetToken.token,
                        })
                        return { success: true }
                    } catch (e) {
                        return { success: false, errorCode: e.code, errorDetail: e.detail }
                    }
                },
            },
        ],
    }),
    listeners: {
        updatePasswordSuccess: async ({ newPasswordResponse }, breakpoint) => {
            if (newPasswordResponse.success) {
                successToast(
                    'Password changed successfully',
                    'Your password was successfully changed. Redirecting you...'
                )
                await breakpoint(3000)
                window.location.href = '/' // We need the refresh
            }
        },
    },
    urlToAction: ({ actions }) => ({
        '/reset/:uuid/:token': ({ uuid, token }) => {
            if (token && uuid) {
                actions.validateResetToken({ uuid, token })
            }
        },
    }),
})
