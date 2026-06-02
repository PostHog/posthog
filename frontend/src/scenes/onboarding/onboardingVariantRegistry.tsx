import { useValues } from 'kea'

import { ProductSelection } from 'scenes/onboarding/productSelection/ProductSelection'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'

/** Control = the entire existing (legacy) onboarding flow (product selection + step host). */
function LegacyOnboarding(): JSX.Element | null {
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
 * To ship an alternative onboarding: add the variant on the PostHog flag, add its component
 * here, and add its chrome (navbar vs. full-viewport) to `ONBOARDING_FLOW_VARIANTS` in
 * `onboardingVariants.ts`. A variant whose chrome is `none` owns the entire viewport — its
 * component renders without any navbar, so it can lay out the whole screen itself.
 */
export const onboardingVariantRegistry: Record<string, () => JSX.Element | null> = {
    control: LegacyOnboarding,
}
