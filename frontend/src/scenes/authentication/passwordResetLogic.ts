import { kea, path, reducers, selectors } from 'kea'
import { forms } from 'kea-forms'
import { loaders } from 'kea-loaders'
import { urlToAction } from 'kea-router'
import posthog from 'posthog-js'

import api from 'lib/api'
import { ValidatedPasswordResult, validatePassword } from 'lib/components/PasswordStrength'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import type { passwordResetLogicType } from './passwordResetLogicType'

export interface ResponseType {
    success: boolean
    errorCode?: string
    errorDetail?: string
}
export interface ResetResponseType extends ResponseType {
    email?: string
}

export interface ValidatedTokenResponseType extends ResponseType {
    token?: string
    uuid?: string
}

export interface PasswordResetForm {
    password: string
    passwordConfirm: string
}

export const passwordResetLogic = kea<passwordResetLogicType>([
    path(['scenes', 'authentication', 'passwordResetLogic']),
    loaders(() => ({
        validatedResetToken: [
            null as ValidatedTokenResponseType | null,
            {
                validateResetToken: async ({ uuid, token }: { uuid: string; token: string }) => {
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
    reducers({
        requestPasswordResetSucceeded: [
            false,
            {
                submitRequestPasswordResetSuccess: () => true,
            },
        ],
        passwordResetSucceeded: [
            false,
            {
                submitPasswordResetSuccess: () => true,
            },
        ],
    }),
    forms(({ values, actions }) => ({
        requestPasswordReset: {
            defaults: {} as unknown as { email: string },
            errors: ({ email }) => ({
                email: !email ? 'Please enter your email to continue' : undefined,
            }),
            submit: async ({ email }, breakpoint) => {
                breakpoint()

                try {
                    await api.create('api/reset/', { email })
                } catch (e: any) {
                    actions.setRequestPasswordResetManualErrors({ email: e.detail ?? 'An error occurred' })
                    posthog.captureException('Failed to reset password', { extra: { error: e } })
                    throw e
                }
            },
        },

        passwordReset: {
            defaults: {} as unknown as PasswordResetForm,
            errors: ({ password, passwordConfirm }) => ({
                password: !password
                    ? 'Please enter your password to continue'
                    : values.validatedPassword.feedback || undefined,
                passwordConfirm: !passwordConfirm
                    ? 'Please confirm your password to continue'
                    : password !== passwordConfirm
                      ? 'Passwords do not match'
                      : undefined,
            }),
            submit: async ({ password }, breakpoint) => {
                await breakpoint(150)

                if (!values.validatedResetToken?.token || !values.validatedResetToken.uuid) {
                    return
                }
                try {
                    const response = await api.create(`api/reset/${values.validatedResetToken.uuid}/`, {
                        password,
                        token: values.validatedResetToken.token,
                    })
                    lemonToast.success('Your password has been changed. Redirecting…')
                    await breakpoint(3000)

                    const url = new URL('/login', window.location.origin)
                    if (response.email) {
                        url.searchParams.set('email', response.email)
                    }
                    window.location.href = url.href // We need the refresh
                } catch (e: any) {
                    actions.setPasswordResetManualErrors({ password: e.detail })
                    throw e
                }
            },
        },
    })),
    selectors({
        validatedPassword: [
            (s) => [s.passwordReset],
            ({ password }): ValidatedPasswordResult => {
                return validatePassword(password)
            },
        ],
    }),
    urlToAction(({ actions }) => ({
        '/reset/:uuid/:token': ({ uuid, token }) => {
            if (token && uuid) {
                actions.validateResetToken({ uuid, token })
            }
        },
        '/reset': (_, { email }) => {
            if (email) {
                actions.setRequestPasswordResetValue('email', email)
            }
        },
    })),
])
