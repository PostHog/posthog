import { FEATURE_FLAGS } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

export function catalogRestructureEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] && !!featureFlags[FEATURE_FLAGS.DATA_CATALOG_RESTRUCTURE]
}
