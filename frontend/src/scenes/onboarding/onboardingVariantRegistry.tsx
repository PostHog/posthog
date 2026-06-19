import { useValues } from 'kea'

import { ProductSelectionShell } from 'scenes/onboarding/productSelection/ProductSelectionShell'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'

function LegacyOnboarding(): JSX.Element | null {
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

export const onboardingVariantRegistry: Record<string, () => JSX.Element | null> = {
    control: LegacyOnboarding,
}
