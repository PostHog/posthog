import { kea } from 'kea'
import { router } from 'kea-router'
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
    token: string
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
                        await api.create('api/reset', { email })
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
                validateResetToken: async ({ token }: { token: string }) => {
                    // TODO: Temp
                    return { success: true, token }
                    try {
                        await api.get(`api/reset/complete?token=${token}`)
                        return { success: true, token }
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
                    if (!values.validatedResetToken?.token) {
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
                        // TODO: await api.create('api/reset/complete', { password, token: values.validatedResetToken.token })
                        successToast(
                            'Password changed successfully',
                            'Your password was successfully changed. Redirecting you...'
                        )
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
                await breakpoint(3000)
                router.actions.push('/')
            }
        },
    },
    urlToAction: ({ actions }) => ({
        '/reset/:token': ({ token }) => {
            if (token) {
                actions.validateResetToken({ token })
            }
        },
    }),
})
