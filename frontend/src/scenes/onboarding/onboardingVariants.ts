import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/** Shipped onboarding variants. `legacy` is the existing experience; `self-driving` is the redesigned one. */
export type OnboardingFlowVariant = 'legacy' | 'self-driving'

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
    'self-driving': { chrome: 'none' },
}

/**
 * Resolve the active flow variant from the raw flag value. The flag's variant values are `control`
 * and `self-driving`; only `self-driving` selects the redesign. Everything else — `control`, the
 * historical `legacy` value (treated as an alias of control), unknown values, booleans, unset —
 * maps to the internal `legacy` variant (the existing design).
 */
export function resolveOnboardingFlowVariant(featureFlags: FeatureFlagsSet): OnboardingFlowVariant {
    const variant = featureFlags[FEATURE_FLAGS.ONBOARDING_FLOW_VARIANT]
    return variant === 'self-driving' ? 'self-driving' : DEFAULT_VARIANT
}

export function onboardingVariantChrome(variant: OnboardingFlowVariant): OnboardingVariantChrome {
    return (ONBOARDING_FLOW_VARIANTS[variant] ?? DEFAULT_VARIANT_CONFIG).chrome
}
