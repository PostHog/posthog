import { useValues } from 'kea'

import { ProductSelection } from 'scenes/onboarding/productSelection/ProductSelection'
import { SceneExport } from 'scenes/sceneTypes'

import { OnboardingFlowHost } from './OnboardingFlowHost'
import { onboardingLogic } from './onboardingLogic'
import { WizardProgressFab } from './sdks/OnboardingInstallStep/WizardProgressFab'

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
 *
 * `WizardProgressFab` mounts at this scope so an in-flight wizard session
 * survives step navigation — the install step renders the full panel,
 * other steps see the FAB.
 */
export function Onboarding(): JSX.Element | null {
    const { productKey } = useValues(onboardingLogic)

    if (!productKey) {
        return <ProductSelection />
    }

    return (
        <div className="pt-4 pb-10">
            <OnboardingFlowHost />
            <WizardProgressFab />
        </div>
    )
}
