/*
Scene to request a password reset email.
*/
import { useActions, useMountedLogic, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'
import { useEffect } from 'react'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { preflightLogic } from 'lib/logic/preflightLogic'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AUTH_NOTES } from 'scenes/authentication/shared/authScene/authNotes'
import { AuthScene, AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { loginTelemetryLogic } from 'scenes/authentication/shared/loginTelemetryLogic'
import { SupportModalButton } from 'scenes/authentication/shared/SupportModalButton'
import { SceneExport } from 'scenes/sceneTypes'

import { passwordResetLogic } from './passwordResetLogic'

export const scene: SceneExport = {
    component: PasswordReset,
    logic: passwordResetLogic,
}

export function PasswordReset(): JSX.Element {
    // Mounted here so the login funnel is only reported from the auth scenes
    useMountedLogic(loginTelemetryLogic)
    const { preflight, preflightLoading } = useValues(preflightLogic)
    const { requestPasswordResetSucceeded, requestPasswordResetManualErrors } = useValues(passwordResetLogic)
    const { resetRequestPasswordReset } = useActions(passwordResetLogic)

    useEffect(() => {
        return () => {
            resetRequestPasswordReset()
        }
    }, [resetRequestPasswordReset])

    const isThrottled = requestPasswordResetManualErrors?.code === 'throttled'
    const emailUnavailable = !preflightLoading && !preflight?.email_service_available
    const notes = emailUnavailable
        ? AUTH_NOTES.passwordReset.emailUnavailable
        : isThrottled
          ? AUTH_NOTES.passwordReset.throttled
          : requestPasswordResetSucceeded
            ? AUTH_NOTES.passwordReset.sent
            : AUTH_NOTES.passwordReset.request

    return (
        <AuthScene notes={notes}>
            <AuthSceneCard footer={<SupportModalButton />}>
                {isThrottled ? (
                    <div className="text-center mb-3">
                        <IconErrorOutline className="text-5xl text-danger" />
                    </div>
                ) : (
                    requestPasswordResetSucceeded && (
                        <div className="text-center mb-3">
                            <IconCheckCircle className="text-5xl text-success" />
                        </div>
                    )
                )}
                <AuthCardTitle
                    title={
                        isThrottled
                            ? 'Too many requests'
                            : requestPasswordResetSucceeded
                              ? 'Check your inbox'
                              : 'Forgot your password?'
                    }
                    sub={
                        !isThrottled && !requestPasswordResetSucceeded && !emailUnavailable
                            ? "Happens to everyone. We'll email you a link."
                            : undefined
                    }
                />
                {preflightLoading ? (
                    <Spinner />
                ) : emailUnavailable ? (
                    <EmailUnavailable />
                ) : isThrottled ? (
                    <ResetThrottled />
                ) : requestPasswordResetSucceeded ? (
                    <ResetSuccess />
                ) : (
                    <ResetForm />
                )}
            </AuthSceneCard>
        </AuthScene>
    )
}

function EmailUnavailable(): JSX.Element {
    return (
        <div className="text-sm">
            <div>
                Self-serve password reset is unavailable. Please <b>contact your instance administrator</b> to reset
                your password.
            </div>
            <LemonDivider className="my-6" />
            <div className="mt-4">
                If you're an administrator:
                <p>
                    <ul>
                        <li>
                            Password reset is unavailable because email service is not configured.{' '}
                            <Link to="https://posthog.com/docs/self-host/configure/email?utm_medium=in-product&utm_campaign=password-reset">
                                Read the docs
                            </Link>{' '}
                            on how to set this up.
                        </li>
                        <li>To reset the password manually, run the following command in your instance.</li>
                    </ul>
                </p>
                <CodeSnippet language={Language.Bash} wrap>
                    python manage.py changepassword [account email]
                </CodeSnippet>
            </div>
        </div>
    )
}

function ResetForm(): JSX.Element {
    const { isRequestPasswordResetSubmitting } = useValues(passwordResetLogic)

    return (
        <Form
            logic={passwordResetLogic}
            formKey="requestPasswordReset"
            className="flex flex-col gap-4"
            enableFormOnSubmit
        >
            <LemonField name="email" label="Email">
                <LemonInput
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="reset-email"
                    placeholder="you@yourcompany.com"
                    type="email"
                    disabled={isRequestPasswordResetSubmitting}
                    fullWidth
                />
            </LemonField>
            <LemonButton
                fullWidth
                type="primary"
                center
                htmlType="submit"
                data-attr="password-reset"
                loading={isRequestPasswordResetSubmitting}
                size="large"
            >
                Continue
            </LemonButton>
        </Form>
    )
}

function ResetSuccess(): JSX.Element {
    const { requestPasswordReset } = useValues(passwordResetLogic)
    const { push } = useActions(router)

    return (
        <div className="text-center text-sm text-secondary">
            Request received successfully! If the email <b>{requestPasswordReset?.email || 'you typed'}</b> exists,
            you’ll receive an email with a reset link soon.
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    data-attr="back-to-login"
                    center
                    fullWidth
                    onClick={() => push('/login')}
                    size="large"
                >
                    Back to login
                </LemonButton>
            </div>
        </div>
    )
}

function ResetThrottled(): JSX.Element {
    const { requestPasswordReset } = useValues(passwordResetLogic)
    const { push } = useActions(router)

    return (
        <div className="text-center text-sm text-secondary">
            There have been too many reset requests for the email <b>{requestPasswordReset?.email || 'you typed'}</b>.
            Please try again later or contact support if you think this has been a mistake.
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    data-attr="back-to-login"
                    center
                    fullWidth
                    onClick={() => push('/login')}
                    size="large"
                >
                    Back to login
                </LemonButton>
            </div>
        </div>
    )
}
