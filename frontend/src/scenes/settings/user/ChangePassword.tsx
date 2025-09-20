import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import PasswordStrength from 'lib/components/PasswordStrength'
import { LemonField } from 'lib/lemon-ui/LemonField'

import { changePasswordLogic } from './changePasswordLogic'

export function ChangePassword(): JSX.Element {
    const { validatedPassword, isChangePasswordSubmitting } = useValues(changePasswordLogic)

    return (
        <Form
            logic={changePasswordLogic}
            formKey="changePassword"
            enableFormOnSubmit
            className="deprecated-space-y-4 max-w-160"
        >
            <LemonField name="current_password" label="Current Password">
                <LemonInput
                    autoComplete="current-password"
                    type="password"
                    className="ph-ignore-input"
                    placeholder="••••••••••"
                />
            </LemonField>

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
                    autoComplete="current-password"
                    type="password"
                    className="ph-ignore-input"
                    placeholder="••••••••••"
                />
            </LemonField>

            <LemonButton type="primary" htmlType="submit" loading={isChangePasswordSubmitting}>
                Change password
            </LemonButton>
        </Form>
    )
}
