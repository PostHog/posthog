import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog, SurprisedHog } from 'lib/components/hedgehogs'

import { emailMFAVerifyLogic } from './emailMFAVerifyLogic'

export function EmailMFAVerify(): JSX.Element {
    const { view, verifyResponseLoading } = useValues(emailMFAVerifyLogic)
    const { verifyAndLogin } = useActions(emailMFAVerifyLogic)

    return (
        <BridgePage view="login" hedgehog>
            <div className="px-12 py-8 text-center flex flex-col items-center max-w-160 w-full">
                {view === 'ready' ? (
                    <>
                        <h1 className="text-3xl font-bold">Email verified!</h1>
                        <div className="max-w-60 mb-12">
                            <HeartHog className="w-full h-full" />
                        </div>
                        <p className="mb-6">Great! Click below to verify your email address.</p>
                        <p className="text-muted text-sm mb-6">This device will be remembered for 30 days</p>
                        <LemonButton
                            type="primary"
                            size="large"
                            fullWidth
                            center
                            onClick={verifyAndLogin}
                            loading={verifyResponseLoading}
                        >
                            Login to PostHog
                        </LemonButton>
                    </>
                ) : view === 'invalid' ? (
                    <>
                        <h1 className="text-3xl font-bold">Whoops!</h1>
                        <div className="max-w-60 mb-12">
                            <SurprisedHog className="w-full h-full" />
                        </div>
                        <LemonButton type="primary" to="/login" fullWidth center>
                            Back to login
                        </LemonButton>
                    </>
                ) : null}
            </div>
        </BridgePage>
    )
}
