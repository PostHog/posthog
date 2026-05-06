import { useValues } from 'kea'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { onboardingLogic } from './onboardingLogic'

/**
 * Renders the current step of an onboarding flow. The flow itself — the list of step
 * descriptors — is built by `onboardingLogic.flow` from the user's selected products
 * and is fully data-driven (no JSX-children walking, no per-product wrapper component).
 */
export function OnboardingFlowHost(): JSX.Element {
    const { product, productKey, currentFlowStep, flow, waitForBilling } = useValues(onboardingLogic)
    const { billingLoading } = useValues(billingLogic)
    const { currentTeam } = useValues(teamLogic)

    const isLoading = (billingLoading && waitForBilling) || !product || !currentFlowStep
    const isMisconfigured = productKey && product && !billingLoading && currentTeam !== null && flow.length === 0

    if (isLoading) {
        return (
            <div className="flex items-center justify-center my-20" role="status" aria-label="Loading onboarding">
                <Spinner className="text-2xl text-secondary w-10 h-10" />
            </div>
        )
    }

    if (isMisconfigured) {
        return (
            <div className="max-w-screen-md mx-auto px-4 py-2">
                <LemonBanner type="error">
                    We couldn't load the onboarding flow for this product. Try{' '}
                    <Link to={urls.onboarding()}>going back to product selection</Link>.
                </LemonBanner>
            </div>
        )
    }

    return currentFlowStep.render()
}
