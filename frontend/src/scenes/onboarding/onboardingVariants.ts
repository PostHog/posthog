import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export type OnboardingFlowVariant = 'legacy' | 'redesign'

/**
 * Chrome rendered around an onboarding variant.
 * - `minimal`: slim top bar (logo + account menu) — the existing onboarding experience.
 * - `none`: no navbar at all; the variant component owns the entire viewport.
 */
export type OnboardingVariantChrome = 'minimal' | 'none'

interface OnboardingVariantConfig {
    chrome: OnboardingVariantChrome
}

const DEFAULT_VARIANT: OnboardingFlowVariant = 'legacy'
const DEFAULT_VARIANT_CONFIG: OnboardingVariantConfig = { chrome: 'minimal' }

export const ONBOARDING_FLOW_VARIANTS: Record<OnboardingFlowVariant, OnboardingVariantConfig> = {
    legacy: { chrome: 'minimal' },
    redesign: { chrome: 'none' },
}

export function resolveOnboardingFlowVariant(featureFlags: FeatureFlagsSet): OnboardingFlowVariant {
    const variant = featureFlags[FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]
    if (variant === 'control') {
        return 'legacy'
    }
    return typeof variant === 'string' && variant in ONBOARDING_FLOW_VARIANTS
        ? (variant as OnboardingFlowVariant)
        : DEFAULT_VARIANT
}

export function onboardingVariantChrome(variant: OnboardingFlowVariant): OnboardingVariantChrome {
    return (ONBOARDING_FLOW_VARIANTS[variant] ?? DEFAULT_VARIANT_CONFIG).chrome
}
