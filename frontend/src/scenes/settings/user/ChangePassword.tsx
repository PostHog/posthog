import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import PasswordStrength from 'lib/components/PasswordStrength'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { userLogic } from 'scenes/userLogic'

import { changePasswordLogic } from './changePasswordLogic'

export function ChangePasswordTitle(): JSX.Element {
    const { user } = useValues(userLogic)
    const hasPassword = user?.has_password ?? false
    return <>{hasPassword ? 'Change password' : 'Set password'}</>
}

export function ChangePassword(): JSX.Element {
    const { validatedPassword, isChangePasswordSubmitting, user } = useValues(changePasswordLogic)
    const hasPassword = user?.has_password ?? false

    return (
        <Form
            logic={changePasswordLogic}
            formKey="changePassword"
            enableFormOnSubmit
            className="deprecated-space-y-4 max-w-160"
        >
            {hasPassword && (
                <LemonField name="current_password" label="Current Password">
                    <LemonInput
                        autoComplete="current-password"
                        type="password"
                        className="ph-ignore-input"
                        placeholder="••••••••••"
                    />
                </LemonField>
            )}

            <LemonField
                name="password"
                label={
                    <div className="flex flex-1 items-center justify-between">
                        <span>Password</span>
                        <PasswordStrength validatedPassword={validatedPassword} />
                    </div>
                }
            >
                <LemonInput
                    autoComplete="new-password"
                    type="password"
                    className="ph-ignore-input"
                    placeholder="••••••••••"
                />
            </LemonField>

            {!hasPassword && (
                <LemonField name="confirm_password" label="Confirm Password">
                    <LemonInput
                        autoComplete="new-password"
                        type="password"
                        className="ph-ignore-input"
                        placeholder="••••••••••"
                    />
                </LemonField>
            )}

            <LemonButton type="primary" htmlType="submit" loading={isChangePasswordSubmitting}>
                {hasPassword ? 'Change password' : 'Set password'}
            </LemonButton>
        </Form>
    )
}
