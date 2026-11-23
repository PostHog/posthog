import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import { Button, Input, Item, ItemContent, ItemDescription } from '@posthog/quill'

import PasswordStrength from 'lib/components/PasswordStrength'
import { QuillSettingFormField } from 'scenes/settings/components/QuillSettingFormField'

import { changePasswordLogic } from './changePasswordLogic'

const PASSWORD_PLACEHOLDER = '••••••••••'

function PasswordInput({
    id,
    value,
    onChange,
    invalid,
    autoComplete,
}: {
    id: string
    value: string | undefined
    onChange: (value: string) => void
    invalid: boolean
    autoComplete: 'current-password' | 'new-password'
}): JSX.Element {
    return (
        <Input
            id={id}
            type="password"
            autoComplete={autoComplete}
            value={value ?? ''}
            onChange={(event) => onChange(event.target.value)}
            aria-invalid={invalid}
            className="ph-ignore-input"
            placeholder={PASSWORD_PLACEHOLDER}
        />
    )
}

export function QuillChangePassword(): JSX.Element {
    const {
        validatedPassword,
        isChangePasswordSubmitting,
        user,
        passwordResetEmailSent,
        passwordResetEmailSentLoading,
    } = useValues(changePasswordLogic)
    const { requestPasswordResetEmail } = useActions(changePasswordLogic)
    const hasPassword = user?.has_password ?? false

    return (
        <Form logic={changePasswordLogic} formKey="changePassword" enableFormOnSubmit className="max-w-160">
            {/* Password managers match a saved login by username, so without one they offer a generated password for the current password too */}
            <input
                type="email"
                name="email"
                autoComplete="username"
                value={user?.email || ''}
                readOnly
                tabIndex={-1}
                aria-hidden
                className="sr-only"
            />
            {/* Spacing lives on this wrapper so the hidden input above does not push the first field down */}
            <div className="flex flex-col gap-4">
                {hasPassword && (
                    <>
                        <QuillSettingFormField
                            name="current_password"
                            label="Current password"
                            labelAction={
                                <Button
                                    size="xs"
                                    data-attr="settings-forgot-password"
                                    onClick={requestPasswordResetEmail}
                                    loading={passwordResetEmailSentLoading}
                                >
                                    {passwordResetEmailSent ? 'Resend link' : 'Forgot password?'}
                                </Button>
                            }
                        >
                            {(control) => <PasswordInput {...control} autoComplete="current-password" />}
                        </QuillSettingFormField>

                        {passwordResetEmailSent && (
                            <Item tone="info" size="sm">
                                <ItemContent>
                                    <ItemDescription>
                                        We emailed a reset link to <span translate="no">{user?.email}</span>. Open it to
                                        set a new password without your current one. Resetting signs you out of PostHog
                                        on every device.
                                    </ItemDescription>
                                </ItemContent>
                            </Item>
                        )}
                    </>
                )}

                <QuillSettingFormField
                    name="password"
                    label="Password"
                    labelAction={<PasswordStrength validatedPassword={validatedPassword} />}
                >
                    {(control) => <PasswordInput {...control} autoComplete="new-password" />}
                </QuillSettingFormField>

                {!hasPassword && (
                    <QuillSettingFormField name="confirm_password" label="Confirm password">
                        {(control) => <PasswordInput {...control} autoComplete="new-password" />}
                    </QuillSettingFormField>
                )}

                <div>
                    <Button variant="primary" type="submit" loading={isChangePasswordSubmitting}>
                        {hasPassword ? 'Change password' : 'Set password'}
                    </Button>
                </div>
            </div>
        </Form>
    )
}
