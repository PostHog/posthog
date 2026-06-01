import { useValues } from 'kea'

import { ProductSelection } from 'scenes/onboarding/productSelection/ProductSelection'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'

/** Control = the entire existing onboarding flow (product selection + step host). */
function ControlOnboarding(): JSX.Element | null {
    const { productKey } = useValues(onboardingLogic)

    if (!productKey) {
        return <ProductSelection />
    }

    return (
        <div className="pt-4 pb-10">
            <OnboardingFlowHost />
        </div>
    )
}

/**
 * Maps an `ONBOARDING_FLOW_VARIANT` flag value to the component that renders that onboarding.
 * Add a new entry here (and a variant on the PostHog flag) to ship an alternative onboarding.
 */
export const onboardingVariantRegistry: Record<string, () => JSX.Element | null> = {
    control: ControlOnboarding,
}
