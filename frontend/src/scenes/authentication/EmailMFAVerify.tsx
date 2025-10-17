import { useValues } from 'kea'

import { Link } from '@posthog/lemon-ui'
import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'

import { emailMFAVerifyLogic } from './emailMFAVerifyLogic'

export function EmailMFAVerify(): JSX.Element {
    const { generalError } = useValues(emailMFAVerifyLogic)
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
                <h2>Verifying your login</h2>

                {generalError ? (
                    <>
                        <LemonBanner type="error">{generalError.detail}</LemonBanner>
                        <div className="mt-4">
                            <Link to="/login">
                                <LemonButton type="primary" fullWidth center size="large">
                                    Back to login
                                </LemonButton>
                            </Link>
                        </div>
                    </>
                ) : (
                    <div className="text-center py-4">
                        <Spinner className="text-4xl" />
                        <p className="mt-4">Please wait while we verify your login...</p>
                        <p className="text-muted text-sm mt-2">This device will be remembered for 30 days</p>
                    </div>
                )}
            </div>
        </BridgePage>
    )
}
