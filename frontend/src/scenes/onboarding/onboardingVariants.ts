import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/** Shipped onboarding variants. `legacy` is the existing experience; `redesign` is the new (stubbed) one. */
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

/**
 * Per-variant configuration consumed by core layout code (navigationLogic) to decide the
 * surrounding chrome. Kept free of React imports so it can be read without pulling the
 * onboarding scene chunk into the main bundle. The matching components live in
 * `onboardingVariantRegistry.tsx` — add a variant in both places to ship a new onboarding.
 */
export const ONBOARDING_FLOW_VARIANTS: Record<OnboardingFlowVariant, OnboardingVariantConfig> = {
    legacy: { chrome: 'minimal' },
    redesign: { chrome: 'minimal' },
}

/**
 * Resolve the active flow variant from the raw flag value, defaulting to `legacy`. Unknown values
 * and the original `control` flag value (which selected the existing design) both map to `legacy`.
 */
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
