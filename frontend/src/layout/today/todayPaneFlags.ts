import { FEATURE_FLAGS, FeatureFlagKey } from 'lib/constants'
import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'

import type { TodayRailPane } from './todayShellLogic'

const TODAY_PANE_FLAGS: Partial<Record<TodayRailPane, FeatureFlagKey>> = {
    release: FEATURE_FLAGS.RELEASES_AREA,
    monitor: FEATURE_FLAGS.MONITOR_AREA,
}

export function isTodayPaneEnabled(pane: TodayRailPane, featureFlags: FeatureFlagsSet): boolean {
    const flag = TODAY_PANE_FLAGS[pane]
    return !flag || !!featureFlags[flag]
}
