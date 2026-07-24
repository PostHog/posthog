import { LegacyOnboarding } from './legacy/LegacyOnboarding'
import type { OnboardingFlowVariant } from './onboardingVariants'
import { SelfDrivingOnboarding } from './self-driving/SelfDrivingOnboarding'

/**
 * Maps each shipped variant to its host component. Add a variant here and in
 * `ONBOARDING_FLOW_VARIANTS` (onboardingVariants.ts) to ship a new onboarding.
 */
export const onboardingVariantRegistry: Record<OnboardingFlowVariant, () => JSX.Element | null> = {
    legacy: LegacyOnboarding,
    'self-driving': SelfDrivingOnboarding,
}
