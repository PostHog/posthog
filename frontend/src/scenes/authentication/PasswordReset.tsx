/*
Scene to request a password reset email.
*/
import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'
import { router } from 'kea-router'

import { IconCheckCircle } from '@posthog/icons'
import { LemonButton, LemonDivider, LemonInput, Link } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { CodeSnippet, Language } from 'lib/components/CodeSnippet'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Spinner } from 'lib/lemon-ui/Spinner/Spinner'
import { IconErrorOutline } from 'lib/lemon-ui/icons'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { SupportModalButton } from './SupportModalButton'
import { passwordResetLogic } from './passwordResetLogic'

export const scene: SceneExport = {
    component: PasswordReset,
    logic: passwordResetLogic,
}

export function PasswordReset(): JSX.Element {
    const { preflight, preflightLoading } = useValues(preflightLogic)
    const { requestPasswordResetSucceeded, requestPasswordResetManualErrors } = useValues(passwordResetLogic)

    return (
        <BridgePage view="password-reset" footer={<SupportModalButton />}>
            {requestPasswordResetManualErrors?.code === 'throttled' ? (
                <div className="text-center ">
                    <IconErrorOutline className="text-5xl text-danger" />
                </div>
            ) : (
                requestPasswordResetSucceeded && (
                    <div className="text-center">
                        <IconCheckCircle className="text-5xl text-success" />
                    </div>
                )
            )}
            <h2>Reset password</h2>
            {preflightLoading ? (
                <Spinner />
            ) : !preflight?.email_service_available ? (
                <EmailUnavailable />
            ) : requestPasswordResetManualErrors?.code === 'throttled' ? (
                <ResetThrottled />
            ) : requestPasswordResetSucceeded ? (
                <ResetSuccess />
            ) : (
                <ResetForm />
            )}
        </BridgePage>
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
            className="deprecated-space-y-4"
            enableFormOnSubmit
        >
            <div className="text-center">
                Enter your email address. If an account exists, you’ll receive an email with a password reset link soon.
            </div>
            <LemonField name="email" label="Email">
                <LemonInput
                    className="ph-ignore-input"
                    autoFocus
                    data-attr="reset-email"
                    placeholder="email@yourcompany.com"
                    type="email"
                    disabled={isRequestPasswordResetSubmitting}
                />
            </LemonField>
            <LemonButton
                fullWidth
                type="primary"
                status="alt"
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
        <div className="text-center">
            Request received successfully! If the email <b>{requestPasswordReset?.email || 'you typed'}</b> exists,
            you’ll receive an email with a reset link soon.
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    status="alt"
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
        <div className="text-center">
            There have been too many reset requests for the email <b>{requestPasswordReset?.email || 'you typed'}</b>.
            Please try again later or contact support if you think this has been a mistake.
            <div className="mt-4">
                <LemonButton
                    type="primary"
                    status="alt"
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
