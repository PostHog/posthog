import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'
import { userLogic } from 'scenes/userLogic'

import { webAnalyticsAchievementsRecordInteraction } from 'products/web_analytics/frontend/generated/api'
import { InteractionKindEnumApi } from 'products/web_analytics/frontend/generated/api.schemas'

import { isWebAnalyticsAchievementsEnabled } from './gating'
import { webAnalyticsAchievementsLogic } from './webAnalyticsAchievementsLogic'

export function recordWebAnalyticsInteraction(kind: InteractionKindEnumApi): void {
    const featureFlags = featureFlagLogic.findMounted()?.values.featureFlags
    const user = userLogic.findMounted()?.values.user
    if (!featureFlags || !isWebAnalyticsAchievementsEnabled(featureFlags, user)) {
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
