import { useActions, useValues } from 'kea'
import { Form } from 'kea-forms'

import * as magnifyingGlassPng from '@posthog/brand/hoggies/png/magnifying-glass'
import { IconCheckCircle } from '@posthog/icons'

import { pngHoggie } from 'lib/brand/hoggies'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { Link } from 'lib/lemon-ui/Link'
import { AuthCardTitle } from 'scenes/authentication/shared/authScene/AuthCardTitle'
import { AuthSceneCard } from 'scenes/authentication/shared/authScene/AuthScene'
import { isValidVerificationCode, normalizeVerificationCode } from 'scenes/authentication/shared/verificationCode'
import { VerificationCodeInput } from 'scenes/authentication/shared/VerificationCodeInput'

import { LoginErrorBanner } from '../components/LoginErrorBanner'
import { loginLogic } from '../loginLogic'

const HedgehogMagnifyingGlass = pngHoggie(magnifyingGlassPng)

export function LoginCodeStep(): JSX.Element {
    const { exitCodeVerification, resendCodeBasedVerification, submitCodeVerification } = useActions(loginLogic)
    const {
        codeVerificationEmail,
        resendResponseLoading,
        resendResponse,
        isCodeVerificationSubmitting,
        codeVerification,
    } = useValues(loginLogic)

    return (
        <AuthSceneCard showPendingConnection>
            <HedgehogMagnifyingGlass className="block w-auto mx-auto mb-3 h-28" />
            <AuthCardTitle
                className="mb-2"
                title="Check your inbox"
                sub={
                    <>
                        For your security, we've emailed a 6-digit verification code to{' '}
                        <strong>{codeVerificationEmail}</strong>.
                    </>
                }
            />
            <div className="mb-5 flex flex-col items-center gap-1 text-sm">
                <Link
                    onClick={() => resendCodeBasedVerification(null)}
                    disabledReason={resendResponseLoading ? 'Sending...' : undefined}
                    className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary"
                >
                    Resend code
                </Link>
                {resendResponse?.success && (
                    <p className="flex items-center gap-1 text-success mb-0" role="status">
                        <IconCheckCircle />
                        <span>Code sent</span>
                    </p>
                )}
            </div>
            <LoginErrorBanner />
            <Form
                logic={loginLogic}
                formKey="codeVerification"
                enableFormOnSubmit
                // The code input renders a hidden input with a \d{6} pattern. Without noValidate,
                // the browser blocks submit on a partial code and kea cannot show its error.
                noValidate
                className="flex flex-col gap-4"
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
                <LemonButton
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
                <div className="flex flex-col items-center gap-3">
                    <Link
                        onClick={() => exitCodeVerification()}
                        className="font-semibold no-underline cursor-pointer hover:underline hover:underline-offset-2 text-secondary"
                    >
                        Back to login
                    </Link>
                </div>
            </Form>
        </AuthSceneCard>
    )
}
