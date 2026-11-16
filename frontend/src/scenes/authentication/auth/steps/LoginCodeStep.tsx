import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import * as mailboxPng from '@posthog/brand/hoggies/png/mailbox'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { OpenInboxLink } from 'scenes/authentication/shared/OpenInboxLink'
import { isValidVerificationCode, normalizeVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'

import { LoginCodeResend } from '../components/LoginCodeResend'
import { LoginErrorBanner } from '../components/LoginErrorBanner'
import { loginLogic } from '../loginLogic'

const HedgehogMailbox = pngHoggie(mailboxPng)

export function LoginCodeStep(): JSX.Element {
    const { exitCodeVerification, submitCodeVerification } = useActions(loginLogic)
    const { codeVerificationEmail, codeVerificationInboxProvider, isCodeVerificationSubmitting, codeVerification } =
        useValues(loginLogic)

    return (
        <AuthSceneCard showPendingConnection>
            <HedgehogMailbox className="block w-auto mx-auto mb-3 h-28" />
            <AuthCardTitle
                className="mb-4"
                title="Check your inbox"
                sub={
                    <>
                        For your security, we've emailed a <span className="whitespace-nowrap">6-digit</span>{' '}
                        verification code to <strong>{codeVerificationEmail}</strong>.{' '}
                        <OpenInboxLink
                            provider={codeVerificationInboxProvider}
                            email={codeVerificationEmail}
                            step="login_code"
                        />
                    </>
                }
            />
            <LoginErrorBanner />
            <Form
                logic={loginLogic}
                formKey="codeVerification"
                enableFormOnSubmit
                // The code input renders a hidden input with a \d{6} pattern. Without noValidate,
                // the browser blocks submit on a partial code and kea cannot show its error.
                noValidate
                className="flex flex-col"
            >
                <LemonField
                    name="code"
                    label="Verification code"
                    labelClassName="sr-only"
                    // Plain centered text without an icon, like the signup verify screen's error
                    renderError={(error) => (
                        <p className="m-0 text-sm text-danger text-center" role="alert">
                            {error}
                        </p>
                    )}
                >
                    <VerificationCodeInput
                        data-attr="code-verification"
                        disabled={isCodeVerificationSubmitting}
                        onComplete={() => {
                            if (!isCodeVerificationSubmitting) {
                                submitCodeVerification()
                            }
                        }}
                    />
                </LemonField>
                <div className="mt-3">
                    <LoginCodeResend />
                </div>
                <LemonButton
                    className="mt-6"
                    type="primary"
                    status="alt"
                    htmlType="submit"
                    data-attr="code-verification-submit"
                    fullWidth
                    center
                    size="large"
                    loading={isCodeVerificationSubmitting}
                    disabledReason={
                        isValidVerificationCode(normalizeVerificationCode(codeVerification.code))
                            ? undefined
                            : 'Enter the 6-digit code from your email'
                    }
                >
                    Verify and log in
                </LemonButton>
                <div className="mt-3 flex justify-center text-sm">
                    <Link
                        onClick={() => exitCodeVerification()}
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary"
                    >
                        ← Back to login
                    </Link>
                </div>
            </Form>
        </AuthSceneCard>
    )
}
