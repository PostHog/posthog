import { useValues } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'

import { onboardingLogic } from './legacy/onboardingLogic'
import { onboardingVariantRegistry } from './onboardingVariantRegistry'
import { resolveOnboardingFlowVariant } from './onboardingVariants'

export const scene: SceneExport = {
    component: Onboarding,
    logic: onboardingLogic,
}

/**
 * Onboarding scene shell.
 */
export function Onboarding(): JSX.Element | null {
    const { featureFlags } = useValues(featureFlagLogic)
    const onboardingFlowVariant = resolveOnboardingFlowVariant(featureFlags)

    const VariantComponent = onboardingVariantRegistry[onboardingFlowVariant] ?? onboardingVariantRegistry.legacy
    return <VariantComponent />
}
