import { useActions, useValues } from 'kea'

import { LemonButton } from '@posthog/lemon-ui'

import { BridgePage } from 'lib/components/BridgePage/BridgePage'
import { HeartHog, SurprisedHog } from 'lib/components/hedgehogs'

import { emailMFAVerifyLogic } from './emailMFAVerifyLogic'

export function EmailMFAVerify(): JSX.Element {
    const { view, verifyResponseLoading } = useValues(emailMFAVerifyLogic)
    const { verifyAndLogin } = useActions(emailMFAVerifyLogic)

    return (
        <BridgePage view="login" fixedWidth={false}>
            <div className="px-12 py-8 text-center flex flex-col items-center max-w-320 w-full">
                {view === 'ready' ? (
                    <>
                        <h1 className="text-3xl font-bold">Almost in - just click below!</h1>
                        <div className="max-w-60 mb-12">
                            <HeartHog className="w-full h-full" />
                        </div>
                        <p className="mb-6">Click below to verify your email address.</p>
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
                        <p className="text-muted text-sm mt-6">This device will be remembered for 30 days</p>
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
