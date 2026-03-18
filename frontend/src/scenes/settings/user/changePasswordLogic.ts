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
    confirm_password: string
}

export const changePasswordLogic = kea<changePasswordLogicType>([
    path(['scenes', 'me', 'settings', 'changePasswordLogic']),
    connect(() => ({
        values: [userLogic, ['user']],
        actions: [userLogic, ['loadUser']],
    })),
    forms(({ values, actions }) => ({
        changePassword: {
            defaults: {} as unknown as ChangePasswordForm,
            errors: ({ current_password, password, confirm_password }) => {
                const hasPassword = values.user?.has_password ?? false
                return {
                    current_password:
                        hasPassword && !current_password ? 'Please enter your current password' : undefined,
                    password: !password
                        ? 'Please enter your password to continue'
                        : values.validatedPassword.feedback || undefined,
                    confirm_password:
                        !hasPassword && !confirm_password
                            ? 'Please confirm your password'
                            : !hasPassword && password !== confirm_password
                              ? 'Passwords do not match'
                              : undefined,
                }
            },
            submit: async ({ password, current_password }, breakpoint) => {
                await breakpoint(150)

                const hasPassword = values.user?.has_password ?? false

                try {
                    await api.update('api/users/@me/', {
                        password,
                        ...(hasPassword ? { current_password } : {}),
                    })
                    actions.resetChangePassword({
                        password: '',
                        current_password: '',
                        confirm_password: '',
                    })
                    lemonToast.success(hasPassword ? 'Password changed' : 'Password set')
                    actions.loadUser()
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
