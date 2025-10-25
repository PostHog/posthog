import { connect, kea, path, selectors } from 'kea'
import { forms } from 'kea-forms'

import { lemonToast } from '@posthog/lemon-ui'

import api from 'lib/api'
import { ValidatedPasswordResult, validatePassword } from 'lib/components/PasswordStrength'
import { userLogic } from 'scenes/userLogic'

import type { changePasswordLogicType } from './changePasswordLogicType'

export interface ChangePasswordForm {
    current_password: string
    password: string
}

export const changePasswordLogic = kea<changePasswordLogicType>([
    path(['scenes', 'me', 'settings', 'changePasswordLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
    })),
    forms(({ values, actions }) => ({
        changePassword: {
            defaults: {} as unknown as ChangePasswordForm,
            errors: ({ current_password, password }) => ({
                current_password:
                    (!values.user || values.user.has_password) && !current_password
                        ? 'Please enter your current password'
                        : undefined,
                password: !password
                    ? 'Please enter your password to continue'
                    : values.validatedPassword.feedback || undefined,
            }),
            submit: async ({ password, current_password }, breakpoint) => {
                await breakpoint(150)

                try {
                    await api.update('api/users/@me/', {
                        current_password,
                        password,
                    })
                    actions.resetChangePassword({ password: '', current_password: '' })
                    lemonToast.success('Password changed')
                } catch (e: any) {
                    setTimeout(() => {
                        // TRICKY: We want to run on the next tick otherwise the errors don't show (possibly because of the async wait in the submit)
                        actions.setChangePasswordManualErrors({ [e.attr]: e.detail })
                    }, 1)
                }
            },
        },
    })),
    selectors({
        validatedPassword: [
            (s) => [s.changePassword],
            ({ password }): ValidatedPasswordResult => {
                return validatePassword(password)
            },
        ],
    }),
])
