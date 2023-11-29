/*
Scene to enter a new password from a received reset link
*/
import { LemonButton, LemonInput } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { Form } from 'kea-forms'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import PasswordStrength from 'lib/components/PasswordStrength'
import { Field } from 'lib/forms/Field'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { SceneExport } from 'scenes/sceneTypes'

import { passwordResetLogic } from './passwordResetLogic'

export const scene: SceneExport = {
    component: PasswordResetComplete,
    logic: passwordResetLogic,
}

export function PasswordResetComplete(): JSX.Element {
    const { validatedResetToken, validatedResetTokenLoading } = useValues(passwordResetLogic)
    const invalidLink = !validatedResetTokenLoading && !validatedResetToken?.success
    return (
        <BridgePage view="password-reset-complete">
            {invalidLink && (
                <div className="text-center mb-2">
                    <IconErrorOutline className="text-muted text-4xl" />
                </div>
            )}
            <h2>{invalidLink ? 'Unable to reset' : 'Set a new password'}</h2>
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
    const { passwordReset, isPasswordResetSubmitting, passwordResetManualErrors } = useValues(passwordResetLogic)

    return (
        <>
            <div className="text-center mb-4">Please enter a new password for your account.</div>
            {!isPasswordResetSubmitting && passwordResetManualErrors.generic && (
                <LemonBanner type="error">
                    {passwordResetManualErrors.generic?.detail ||
                        'Could not complete your password reset request. Please try again.'}
                </LemonBanner>
            )}
            <Form logic={passwordResetLogic} formKey={'passwordReset'} className="space-y-4" enableFormOnSubmit>
                <Field
                    name="password"
                    label={
                        <div className="flex flex-1 items-center justify-between">
                            <span>Password</span>
                            <span className="w-20">
                                <PasswordStrength password={passwordReset.password} />
                            </span>
                        </div>
                    }
                >
                    <LemonInput
                        autoComplete="new-password"
                        type="password"
                        className="ph-ignore-input"
                        placeholder="••••••••••"
                        data-attr="password"
                    />
                </Field>

                <Field name="passwordConfirm" label="Confirm Password">
                    <LemonInput
                        autoComplete="new-password"
                        type="password"
                        className="ph-ignore-input"
                        placeholder="••••••••••"
                        data-attr="password-confirm"
                    />
                </Field>

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
    return (
        <div className="text-center">
            The provided link is <b>invalid or has expired</b>. Please request a new link.
            <div className="mt-4">
                <LemonButton fullWidth type="primary" center data-attr="back-to-login" to={'/reset'}>
                    Request new link
                </LemonButton>
            </div>
        </div>
    )
}
