import { useValues } from 'kea'

import { SceneExport } from 'scenes/sceneTypes'

import { onboardingLogic } from './onboardingLogic'
import { onboardingVariantRegistry } from './onboardingVariantRegistry'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Onboarding scene shell.
 *
 * Reads the `ONBOARDING_FLOW_VARIANT` multivariate flag and renders the matching onboarding
 * variant from {@link onboardingVariantRegistry}. `control` (the default, and the fallback for
 * any unknown value) renders the current product-selection + step-host flow.
 */
export function Onboarding(): JSX.Element | null {
    const { onboardingFlowVariant } = useValues(onboardingLogic)
    const VariantComponent = onboardingVariantRegistry[onboardingFlowVariant] ?? onboardingVariantRegistry.control
    return <VariantComponent />
}
