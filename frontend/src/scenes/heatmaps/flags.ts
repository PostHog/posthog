import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export function isPrewarmEnabled(featureFlags: FeatureFlagsSet): boolean {
    const variant = featureFlags[FEATURE_FLAGS.HEATMAPS_SCREENSHOT_PREWARM]
    return variant === true || variant === 'test'
}
