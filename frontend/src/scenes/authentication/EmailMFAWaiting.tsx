import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { emailMFAWaitingLogic } from './emailMFAWaitingLogic'

export function EmailMFAWaiting(): JSX.Element {
    const { generalError, resendEmailResponseLoading, resendSuccess } = useValues(emailMFAWaitingLogic)
    const { resendEmail } = useActions(emailMFAWaitingLogic)
    const { preflight } = useValues(preflightLogic)

    return (
        <BridgePage
            view="login"
            hedgehog
            message={
                <>
                    Welcome to
                    <br /> PostHog{preflight?.cloud ? ' Cloud' : ''}!
                </>
            }
        >
            <div className="deprecated-space-y-2">
                <h2>Check your email</h2>
                <p>
                    We've sent a verification link to your email address. Click the link in the email to complete your
                    login.
                </p>

                {generalError && <LemonBanner type="error">{generalError.detail}</LemonBanner>}
                {resendSuccess && <LemonBanner type="success">Verification email sent! Check your inbox.</LemonBanner>}

                <div className="deprecated-space-y-4 mt-4">
                    <p className="text-muted text-sm">Didn't receive the email?</p>
                    <LemonButton
                        type="secondary"
                        fullWidth
                        center
                        onClick={resendEmail}
                        loading={resendEmailResponseLoading}
                        size="large"
                    >
                        Resend verification email
                    </LemonButton>
                </div>
            </div>
        </BridgePage>
    )
}
