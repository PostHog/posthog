/*
Scene to enter a new password from a received reset link
*/
import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import PasswordStrength from 'lib/components/PasswordStrength'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { PASSWORD_ALREADY_RESET_CODE, passwordResetLogic } from './passwordResetLogic'

export const scene: SceneExport = {
    component: PasswordResetComplete,
    logic: passwordResetLogic,
}

export function PasswordResetComplete(): JSX.Element {
    const { validatedResetToken, validatedResetTokenLoading } = useValues(passwordResetLogic)
    const invalidLink = !validatedResetTokenLoading && !validatedResetToken?.success
    const alreadyReset = validatedResetToken?.errorCode === PASSWORD_ALREADY_RESET_CODE

    let title = 'Set a new password'
    if (invalidLink) {
        title = alreadyReset ? 'Password already changed' : 'Unable to reset'
    }

    return (
        <BridgePage view="password-reset-complete">
            {invalidLink && (
                <div className="text-center mb-2">
                    <IconErrorOutline className="text-secondary text-4xl" />
                </div>
            )}
            <h2>{title}</h2>
            {validatedResetTokenLoading ? (
                <Spinner />
            ) : !validatedResetToken?.token ? (
                <ResetInvalid />
            ) : (
                <NewPasswordForm />
            )}
        </BridgePage>
    )
}

function NewPasswordForm(): JSX.Element {
    const { validatedPassword, isPasswordResetSubmitting, passwordResetManualErrors } = useValues(passwordResetLogic)

    return (
        <>
            <div className="text-center mb-4">Please enter a new password for your account.</div>
            {!isPasswordResetSubmitting && passwordResetManualErrors.generic && (
                <LemonBanner type="error">
                    {passwordResetManualErrors.generic?.detail ||
                        'Could not complete your password reset request. Please try again.'}
                </LemonBanner>
            )}
            <Form
                logic={passwordResetLogic}
                formKey="passwordReset"
                className="deprecated-space-y-4"
                enableFormOnSubmit
            >
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
                        data-attr="password"
                        autoFocus
                    />
                </LemonField>

                <LemonField name="passwordConfirm" label="Confirm Password">
                    <LemonInput
                        autoComplete="new-password"
                        type="password"
                        className="ph-ignore-input"
                        placeholder="••••••••••"
                        data-attr="password-confirm"
                    />
                </LemonField>

                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="password-reset-complete"
                    loading={isPasswordResetSubmitting}
                >
                    Change my password
                </LemonButton>
            </Form>
        </>
    )
}

function ResetInvalid(): JSX.Element {
    const { user } = useValues(userLogic)
    const { validatedResetToken } = useValues(passwordResetLogic)

    const action =
        validatedResetToken?.errorCode === PASSWORD_ALREADY_RESET_CODE
            ? { label: 'Log in', to: urls.login(), dataAttr: 'log-in' }
            : {
                  label: 'Request new link',
                  // Scene.PasswordReset is onlyUnauthenticated, so /reset would bounce a signed-in user.
                  to: user ? urls.settings('user-profile', 'change-password') : urls.passwordReset(),
                  dataAttr: 'back-to-login',
              }

    return (
        <div className="text-center">
            {validatedResetToken?.errorDetail ||
                'This reset link is not valid. Request a new one to set your password.'}
            <div className="mt-4">
                <LemonButton fullWidth type="primary" center data-attr={action.dataAttr} to={action.to}>
                    {action.label}
                </LemonButton>
            </div>
        </div>
    )
}
