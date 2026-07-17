import { useValues } from 'kea'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'
import { ProductSelectionShell } from './productSelection/ProductSelectionShell'

/**
 * Host for the existing ("legacy") onboarding experience. Renders product selection until a
 * product is chosen, then hands off to the flow host. Selected via `onboardingVariantRegistry`.
 */
export function LegacyOnboarding(): JSX.Element | null {
    const { productKey } = useValues(onboardingLogic)

    if (!productKey) {
        return <ProductSelectionShell />
    }

    return (
        <div className="pt-4 pb-10">
            <OnboardingFlowHost />
        </div>
    )
}
