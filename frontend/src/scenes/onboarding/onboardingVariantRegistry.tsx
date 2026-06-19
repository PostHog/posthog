import { LegacyOnboarding } from './legacy/LegacyOnboarding'
import type { OnboardingFlowVariant } from './onboardingVariants'
// The redesign host is the canonical `Onboarding`; aliased here so it reads distinctly next to `LegacyOnboarding`.
import { Onboarding as RedesignOnboarding } from './redesign/Onboarding'

/**
 * Maps each shipped variant to its host component. Add a variant here and in
 * `ONBOARDING_FLOW_VARIANTS` (onboardingVariants.ts) to ship a new onboarding.
 */
export const onboardingVariantRegistry: Record<OnboardingFlowVariant, () => JSX.Element | null> = {
    legacy: LegacyOnboarding,
    redesign: RedesignOnboarding,
}
