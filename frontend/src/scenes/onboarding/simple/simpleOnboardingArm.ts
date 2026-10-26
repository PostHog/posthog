import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

/** Reading the flag reports an experiment exposure, so call this only where the arm decides something. */
export function isOnSimpleOnboardingArm(featureFlags: FeatureFlagsSet): boolean {
    return featureFlags[FEATURE_FLAGS.ONBOARDING_SIMPLE_FLOW] === 'test'
}
