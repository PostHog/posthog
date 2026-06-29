import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import { UserType } from '~/types'

export function isWebAnalyticsAchievementsEnabled(featureFlags: FeatureFlagsSet, user?: UserType | null): boolean {
    if (user?.web_analytics_achievements_opt_out) {
        return false
    }
    return (
        !!featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS] &&
        featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_STREAK_CADENCE] !== 'control'
    )
}
