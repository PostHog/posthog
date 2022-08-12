/*
Scene to request a password reset email.
*/
import React from 'react'
import { WelcomeLogo } from './WelcomeLogo'
import { CheckCircleOutlined } from '@ant-design/icons'
import { useActions, useValues } from 'kea'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { CodeSnippet, Language } from 'scenes/ingestion/frameworks/CodeSnippet'
import { passwordResetLogic } from './passwordResetLogic'
import { router } from 'kea-router'
import { SceneExport } from 'scenes/sceneTypes'
import { Spinner } from 'lib/components/Spinner/Spinner'
import { LemonButton, LemonDivider, LemonInput } from '@posthog/lemon-ui'
import { Form } from 'kea-forms'
import { Field } from 'lib/forms/Field'
import { AuthenticationButton } from './AuthenticationButton'

export const scene: SceneExport = {
    component: PasswordReset,
    logic: passwordResetLogic,
}

export function PasswordReset(): JSX.Element {
    const { preflight, preflightLoading } = useValues(preflightLogic)
    const { requestPasswordResetSucceeded } = useValues(passwordResetLogic)

    return (
        <div className="BridgePage password-reset">
            <div className="AuthContent">
                <WelcomeLogo view="login" />
                <div className="inner">
                    {requestPasswordResetSucceeded && (
                        <div className="text-center">
                            <CheckCircleOutlined style={{ color: 'var(--success)', fontSize: '4em' }} />
                        </div>
                    )}
                    <h2 className="subtitle justify-center">Reset password</h2>
                    {preflightLoading ? (
                        <Spinner />
                    ) : !preflight?.email_service_available ? (
                        <EmailUnavailable />
                    ) : requestPasswordResetSucceeded ? (
                        <ResetSuccess />
                    ) : (
                        <ResetForm />
                    )}
                </div>
            </div>
        </div>
    )
}

function EmailUnavailable(): JSX.Element {
    return (
        <div>
            <div>
                Self-serve password reset is unavailable. Please <b>contact your instance administrator</b> to reset
                your password.
            </div>
            <LemonDivider className="my-6" />
            <div className="mt-4">
                If you're an administrator:
                <ul>
                    <li>
                        Password reset is unavailable because email service is not configured.{' '}
                        <a href="https://posthog.com/docs/self-host/configure/email?utm_medium=in-product&utm_campaign=password-reset">
                            Read the docs
                        </a>{' '}
                        on how to set this up.
                    </li>
                    <li>To reset the password manually, run the following command in your instance.</li>
                </ul>
                <CodeSnippet language={Language.Bash} wrap>
                    {'python manage.py changepassword [account email]'}
                </CodeSnippet>
            </div>
        </div>
    )
}

function ResetForm(): JSX.Element {
    const { isRequestPasswordResetSubmitting } = useValues(passwordResetLogic)

    return (
        <Form logic={passwordResetLogic} formKey={'requestPasswordReset'} className="space-y-4" enableFormOnSubmit>
            <div className="text-center">
                Enter your email address. If an account exists, you’ll receive an email with a password reset link soon.
            </div>
            {/* {!isRequestPasswordResetSubmitting && resetResponse?.errorCode && (
                <AlertMessage type="error">
                    {resetResponse.errorDetail || 'Could not complete your password reset request. Please try again.'}
                </AlertMessage>
            )} */}
            <Field name="email" label="Email">
                <LemonInput
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="reset-email"
                    placeholder="email@yourcompany.com"
                    type="email"
                    disabled={isRequestPasswordResetSubmitting}
                />
            </Field>
            <AuthenticationButton
                htmlType="submit"
                data-attr="password-reset"
                loading={isRequestPasswordResetSubmitting}
            >
                Continue
            </AuthenticationButton>
        </Form>
    )
}

function ResetSuccess(): JSX.Element {
    const { requestPasswordReset } = useValues(passwordResetLogic)
    const { push } = useActions(router)

    return (
        <div className="text-center">
            Request received successfully! If the email <b>{requestPasswordReset?.email || 'you typed'}</b> exists,
            you’ll receive an email with a reset link soon.
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    status="primary-alt"
                    size="large"
                    data-attr="back-to-login"
                    center
                    fullWidth
                    onClick={() => push('/login')}
                >
                    Back to login
                </LemonButton>
            </div>
        </div>
    )
}
