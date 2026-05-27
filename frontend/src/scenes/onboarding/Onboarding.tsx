import { useValues } from 'kea'

import { ProductSelection } from 'scenes/onboarding/productSelection/ProductSelection'
import { SceneExport } from 'scenes/sceneTypes'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Onboarding scene shell.
 *
 * - No `productKey` in the URL → render the product-selection landing page.
 * - With a `productKey` → hand off to {@link OnboardingFlowHost}, which renders the
 *   current step out of the data-driven flow built by `onboardingLogic.flow`.
 */
export function Onboarding(): JSX.Element | null {
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
