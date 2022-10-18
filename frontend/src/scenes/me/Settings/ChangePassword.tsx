import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import PasswordStrength from 'lib/components/PasswordStrength'
import { changePasswordLogic } from './changePasswordLogic'

export function ChangePassword(): JSX.Element {
    const { changePassword, isChangePasswordSubmitting } = useValues(changePasswordLogic)

    return (
        <Form
            logic={changePasswordLogic}
            formKey="changePassword"
            enableFormOnSubmit
            className="space-y-4"
            style={{ maxWidth: '40rem' }}
        >
            <Field name="current_password" label={'Current Password'}>
                <LemonInput
                    autoComplete="current-password"
                    type="password"
                    className="ph-ignore-input"
                    placeholder="••••••••••"
                />
            </Field>

            <Field
                name="password"
                label={
                    <div className="flex flex-1 items-center justify-between">
                        <span>Password</span>
                        <span className="w-20">
                            <PasswordStrength password={changePassword.password} />
                        </span>
                    </div>
                }
            >
                <LemonInput
                    autoComplete="current-password"
                    type="password"
                    className="ph-ignore-input"
                    placeholder="••••••••••"
                />
            </Field>

            <LemonButton type="primary" htmlType="submit" loading={isChangePasswordSubmitting}>
                Change password
            </LemonButton>
        </Form>
    )
}
