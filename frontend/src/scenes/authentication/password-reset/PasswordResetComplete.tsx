/*
Scene to enter a new password from a received reset link
*/
import { useValues } from 'kea'
import { Form } from 'kea-forms'

import { LemonButton, LemonInput } from '@posthog/lemon-ui'

import PasswordStrength from 'lib/components/PasswordStrength'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { AuthBanner } from 'scenes/authentication/shared/authScene/AuthBanner'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { SceneExport } from 'scenes/sceneTypes'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { passwordResetLogic } from './passwordResetLogic'

export const scene: SceneExport = {
    component: PasswordResetComplete,
    logic: passwordResetLogic,
}

export function PasswordResetComplete(): JSX.Element {
    const { validatedResetToken, validatedResetTokenLoading } = useValues(passwordResetLogic)
    const invalidLink = !validatedResetTokenLoading && !validatedResetToken?.success
    return (
        <AuthScene
            notes={
                invalidLink ? AUTH_NOTES.passwordResetComplete.invalid : AUTH_NOTES.passwordResetComplete.newPassword
            }
        >
            <AuthSceneCard>
                {invalidLink && (
                    <div className="text-center mb-3">
                        <IconErrorOutline className="text-secondary text-5xl" />
                    </div>
                )}
                <AuthCardTitle
                    title={invalidLink ? 'Unable to reset' : 'Set a new password'}
                    sub={invalidLink || validatedResetTokenLoading ? undefined : 'Make it a good one.'}
                />
                {validatedResetTokenLoading ? (
                    <Spinner />
                ) : !validatedResetToken?.token ? (
                    <ResetInvalid />
                ) : (
                    <NewPasswordForm />
                )}
            </AuthSceneCard>
        </AuthScene>
    )
}

function NewPasswordForm(): JSX.Element {
    const { validatedPassword, isPasswordResetSubmitting, passwordResetManualErrors } = useValues(passwordResetLogic)

    return (
        <>
            {!isPasswordResetSubmitting && passwordResetManualErrors.generic && (
                <AuthBanner variant="danger" className="mb-4">
                    {passwordResetManualErrors.generic?.detail ||
                        'Could not complete your password reset request. Please try again.'}
                </AuthBanner>
            )}
            <Form logic={passwordResetLogic} formKey="passwordReset" className="flex flex-col gap-4" enableFormOnSubmit>
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
                        fullWidth
                    />
                </LemonField>

                <LemonField name="passwordConfirm" label="Confirm password">
                    <LemonInput
                        autoComplete="new-password"
                        type="password"
                        className="ph-ignore-input"
                        placeholder="••••••••••"
                        data-attr="password-confirm"
                        fullWidth
                    />
                </LemonField>

                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    htmlType="submit"
                    data-attr="password-reset-complete"
                    loading={isPasswordResetSubmitting}
                    size="large"
                >
                    Change my password
                </LemonButton>
            </Form>
        </>
    )
}

function ResetInvalid(): JSX.Element {
    const { user } = useValues(userLogic)

    return (
        <div className="text-center text-sm text-secondary">
            The provided link is <b>invalid or has expired</b>. Please request a new link.
            <div className="mt-4">
                <LemonButton
                    fullWidth
                    type="primary"
                    center
                    data-attr="back-to-login"
                    size="large"
                    // Scene.PasswordReset is onlyUnauthenticated, so /reset would bounce a signed-in user.
                    to={user ? urls.settings('user-profile', 'change-password') : urls.passwordReset()}
                >
                    Request new link
                </LemonButton>
            </div>
        </div>
    )
}
