import { useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import { LemonBanner, Link, Spinner } from '@posthog/lemon-ui'

import { billingLogic } from 'scenes/billing/billingLogic'
import { teamLogic } from 'scenes/teamLogic'
import { urls } from 'scenes/urls'

import { onboardingLogic } from './onboardingLogic'

export function OnboardingFlowHost(): JSX.Element {
    const { product, productKey, currentFlowStep, flow, waitForBilling } = useValues(onboardingLogic)
    const { billingLoading } = useValues(billingLogic)
    const { currentTeam } = useValues(teamLogic)

    const isMisconfigured = productKey && product && !billingLoading && currentTeam !== null && flow.length === 0
    const isLoading = !isMisconfigured && ((billingLoading && waitForBilling) || !product || !currentFlowStep)

    useEffect(() => {
        if (isMisconfigured) {
            posthog.captureException(new Error('Onboarding flow misconfigured: product registered but no flow steps'), {
                productKey,
            })
        }
    }, [isMisconfigured, productKey])

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

    if (isLoading || !currentFlowStep) {
        return (
            <div className="flex items-center justify-center my-20" role="status" aria-label="Loading onboarding">
                <Spinner className="text-2xl text-secondary w-10 h-10" />
            </div>
        )
    }

    return currentFlowStep.render()
}
