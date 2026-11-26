import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { TodayRailPane } from './todayShellLogic'

const TODAY_PANE_FLAGS: Partial<Record<TodayRailPane, FeatureFlagKey>> = {
    release: FEATURE_FLAGS.RELEASES_AREA,
    monitor: FEATURE_FLAGS.MONITOR_AREA,
    // Automate shares Data's flag, because Destinations move from Data to Automate and neither pane should show alone.
    automate: FEATURE_FLAGS.DATA_AREA,
    data: FEATURE_FLAGS.DATA_AREA,
}

/** Home is always on the rail. This flag only decides whether it opens a pane, or hides the sidebar as before. */
export function isTodayHomePaneEnabled(featureFlags: FeatureFlagsSet): boolean {
    return !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV] && !!featureFlags[FEATURE_FLAGS.TODAY_HOME_PANE]
}

export function isTodayPaneEnabled(pane: TodayRailPane, featureFlags: FeatureFlagsSet): boolean {
    const flag = TODAY_PANE_FLAGS[pane]
    return !flag || !!featureFlags[flag]
}
