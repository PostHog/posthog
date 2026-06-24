import { LegacyOnboarding } from './legacy/LegacyOnboarding'
import type { OnboardingFlowVariant } from './onboardingVariants'
import { RedesignOnboarding } from './redesign/RedesignOnboarding'

/**
 * Maps each shipped variant to its host component. Add a variant here and in
 * `ONBOARDING_FLOW_VARIANTS` (onboardingVariants.ts) to ship a new onboarding.
 */
export const onboardingVariantRegistry: Record<OnboardingFlowVariant, () => JSX.Element | null> = {
    legacy: LegacyOnboarding,
    redesign: RedesignOnboarding,
}
