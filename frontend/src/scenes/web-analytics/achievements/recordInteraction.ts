import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { webAnalyticsAchievementsRecordInteraction } from 'products/web_analytics/frontend/generated/api'
import { InteractionKindEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { isWebAnalyticsAchievementsEnabled } from './gating'
import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'
import { webAnalyticsAchievementsPreferencesLogic } from './webAnalyticsAchievementsPreferencesLogic'

export function recordWebAnalyticsInteraction(kind: InteractionKindEnumApi): void {
    const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags
    const optedOut = webAnalyticsAchievementsPreferencesLogic.findMounted()?.values.achievementsOptOut
    if (!featureFlags || !isWebAnalyticsAchievementsEnabled(featureFlags, optedOut)) {
        return
    }
    const projectId = teamLogic.findMounted()?.values.currentProjectId
    if (projectId === undefined || projectId === null) {
        return
    }
    void webAnalyticsAchievementsRecordInteraction(String(projectId), { interaction_kind: kind })
        .then(() => {
            webAnalyticsAchievementsLogic.findMounted()?.actions.loadAchievements()
        })
        .catch(() => {})
}
