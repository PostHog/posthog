import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export function isWebAnalyticsAchievementsEnabled(featureFlags: FeatureFlagsSet, optedOut?: boolean): boolean {
    if (optedOut) {
        return false
    }
    return (
        !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS] &&
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE] !== 'control'
    )
}
