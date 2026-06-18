import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export type AuthFlowVariant = 'legacy' | 'redesign-2026-06-02'

const DEFAULT_VARIANT: AuthFlowVariant = 'legacy'

export const AUTH_FLOW_VARIANTS: AuthFlowVariant[] = ['legacy', 'redesign-2026-06-02']

export function resolveAuthFlowVariant(featureFlags: FeatureFlagsSet): AuthFlowVariant {
    const variant = featureFlags[FEATURE_FLAGS.AUTH_FLOW_VARIANT]
    return typeof variant === 'string' && (AUTH_FLOW_VARIANTS as string[]).includes(variant)
        ? (variant as AuthFlowVariant)
        : DEFAULT_VARIANT
}
