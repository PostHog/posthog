/*
Scene to enter a new password from a received reset link
*/
import React from 'react'
import { useValues } from 'kea'
import { passwordResetLogic } from './passwordResetLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { Field } from 'lib/forms/Field'
import { LemonInput } from '@posthog/lemon-ui'
import PasswordStrength from 'lib/components/PasswordStrength'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { Form } from 'kea-forms'
import { AlertMessage } from 'lib/components/AlertMessage'
import { AuthenticationButton } from './AuthenticationButton'
import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { IconErrorOutline } from 'lib/components/icons'

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
                <AlertMessage type="error">
                    {passwordResetManualErrors.generic?.detail ||
                        'Could not complete your password reset request. Please try again.'}
                </AlertMessage>
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
                    <LemonInput type="password" className="ph-ignore-input" placeholder="••••••••••" />
                </Field>

                <Field name="passwordConfirm" label="Confirm Password">
                    <LemonInput type="password" className="ph-ignore-input" placeholder="••••••••••" />
                </Field>

                <AuthenticationButton
                    htmlType="submit"
                    data-attr="password-reset-complete"
                    loading={isPasswordResetSubmitting}
                >
                    Change my password
                </AuthenticationButton>
            </Form>
        </>
    )
}

function ResetInvalid(): JSX.Element {
    return (
        <div className="text-center">
            The provided link is <b>invalid or has expired</b>. Please request a new link.
            <div className="mt-4">
                <AuthenticationButton data-attr="back-to-login" to={'/reset'}>
                    Request new link
                </AuthenticationButton>
            </div>
        </div>
    )
}
