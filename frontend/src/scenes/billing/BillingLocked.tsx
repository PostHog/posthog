import { useValues } from 'kea'
import { SceneExport } from 'scenes/sceneTypes'
import { billingLogic } from './billingLogic'
import { BillingSubscribedTheme } from './BillingSubscribed'
import { compactNumber } from 'lib/utils'
import { LemonButton } from '@posthog/lemon-ui'
import { IconCancel } from 'lib/components/icons'
import { BillingLockedV2 } from './v2/BillingLocked'
import { SpinnerOverlay } from 'lib/components/Spinner/Spinner'

export const scene: SceneExport = {
    component: BillingLocked,
}

export function BillingLocked(): JSX.Element | null {
    const { billing, billingVersion } = useValues(billingLogic)

    if (!billingVersion) {
        return <SpinnerOverlay />
    }

    if (billingVersion === 'v2') {
        return <BillingLockedV2 />
    }

    return (
        <BillingSubscribedTheme>
            <div className="flex items-center gap-2">
                <IconCancel className="text-danger text-3xl mb-2" />
                <h2>Please enter a credit card</h2>
            </div>
            <p>
                You've used{' '}
                <strong>{billing?.current_usage ? compactNumber(billing?.current_usage) : 'all your'}</strong> events
                this month. To continue using PostHog, you'll need to enter a credit card. See{' '}
                <a href="https://posthog.com/pricing" target="_blank">
                    our website for pricing information.
                </a>
                <br />
                <br />
                You'll only be charged for events from the moment you put your credit card details in.
            </p>
            <div className="mt text-center">
                <LemonButton
                    className="cta-button"
                    type="primary"
                    center={true}
                    fullWidth
                    to={billing?.subscription_url}
                    disableClientSideRouting
                >
                    Continue to verify card
                </LemonButton>
            </div>
        </BillingSubscribedTheme>
    )
}
