import { afterMount, connect, kea, listeners, path, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import {
    webAnalyticsAchievementsPreferences,
    webAnalyticsAchievementsUpdatePreferences,
} from 'products/web_analytics/frontend/generated/api'
import type { WebAnalyticsUserPreferencesApi } from 'products/web_analytics/frontend/generated/api.schemas'

import type { webAnalyticsAchievementsPreferencesLogicType } from './webAnalyticsAchievementsPreferencesLogicType'

export const webAnalyticsAchievementsPreferencesLogic = kea<webAnalyticsAchievementsPreferencesLogicType>([
    path(['scenes', 'web-analytics', 'achievements', 'webAnalyticsAchievementsPreferencesLogic']),
    connect(() => ({
        values: [teamLogic, ['currentProjectId'], featureFlagLogic, ['featureFlags']],
    })),
    loaders(({ values }) => ({
        preferences: [
            null as WebAnalyticsUserPreferencesApi | null,
            {
                loadPreferences: async () => {
                    return await webAnalyticsAchievementsPreferences(String(values.currentProjectId))
                },
                setAchievementsOptOut: async ({ optedOut }: { optedOut: boolean }) => {
                    return await webAnalyticsAchievementsUpdatePreferences(String(values.currentProjectId), {
                        achievements_opt_out: optedOut,
                    })
                },
            },
        ],
    })),
    selectors({
        achievementsOptOut: [
            (s) => [s.preferences],
            (preferences): boolean => preferences?.achievements_opt_out ?? false,
        ],
    }),
    listeners({
        setAchievementsOptOut: ({ optedOut }) => {
            posthog.capture('web_analytics_achievements_opt_out_toggled', { opted_out: optedOut })
        },
    }),
    afterMount(({ actions, values }) => {
        if (values.featureFlags[FEATURE_FLAGS.WEB_ANALYTICS_ACHIEVEMENTS]) {
            actions.loadPreferences()
        }
    }),
])
