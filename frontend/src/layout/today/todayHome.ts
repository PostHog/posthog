import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isUnderPath } from 'lib/utils/kea-router'
import { urls } from 'scenes/urls'

import { isTodayHomePaneEnabled, isTodayPaneEnabled } from './todayPaneFlags'

export function isHomePanePath(path: string): boolean {
    return (
        path === urls.inbox() ||
        isUnderPath(path, urls.inbox('reports')) ||
        isUnderPath(path, urls.inbox('monitoring')) ||
        isUnderPath(path, urls.inbox('settings')) ||
        isUnderPath(path, urls.pulse())
    )
}

/** Inbox sources belong to Data, so they open it only while the Data pane is on as well. */
export function homePaneRouteForPath(path: string, featureFlags: FeatureFlagsSet): 'home' | 'data' | null {
    if (!isTodayHomePaneEnabled(featureFlags)) {
        return null
    }
    if (isHomePanePath(path)) {
        return 'home'
    }
    return isTodayPaneEnabled('data', featureFlags) && isUnderPath(path, urls.inbox('sources')) ? 'data' : null
}
