import { useValues } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'

/** The canvas scenes ship with the rail navigation, and with small software apps in the standard navigation. */
export function canvasScenesEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] || !!featureFlags[FEATURE_FLAGS.SMALL_SOFTWARE_APPS]
}

/** The Spaces scene only exists in the rail navigation, so a space link elsewhere would open a missing page. */
export function spaceLinksEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV]
}

export function useCanvasScenesEnabled(): boolean {
    const { featureFlags } = useValues(featureFlagLogic)
    return canvasScenesEnabled(featureFlags)
}
