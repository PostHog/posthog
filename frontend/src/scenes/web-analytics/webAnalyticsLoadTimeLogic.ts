import { actions, afterMount, connect, kea, listeners, path, reducers, sharedListeners } from 'kea'
import posthog from 'posthog-js'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { teamLogic } from 'scenes/teamLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

import { webAnalyticsAchievementsRecordVisit } from 'products/web_analytics/frontend/generated/api'

import { isWebAnalyticsAchievementsEnabled } from './achievements/gating'
import { webAnalyticsAchievementsLogic } from './achievements/webAnalyticsAchievementsLogic'
import { webAnalyticsAchievementsPreferencesLogic } from './achievements/webAnalyticsAchievementsPreferencesLogic'
import { WEB_ANALYTICS_DATA_COLLECTION_NODE_ID } from './common'
import type { webAnalyticsLoadTimeLogicType } from './webAnalyticsLoadTimeLogicType'

export const webAnalyticsLoadTimeLogic = kea<webAnalyticsLoadTimeLogicType>([
    path(['scenes', 'webAnalytics', 'webAnalyticsLoadTimeLogic']),
    connect(() => ({
        actions: [
            dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }),
            ['collectionNodeLoadData', 'collectionNodeLoadDataSuccess', 'collectionNodeLoadDataFailure'],
        ],
        values: [
            dataNodeCollectionLogic({ key: WEB_ANALYTICS_DATA_COLLECTION_NODE_ID }),
            ['areAnyLoading'],
            featureFlagLogic,
            ['featureFlags'],
            teamLogic,
            ['currentProjectId'],
            webAnalyticsAchievementsPreferencesLogic,
            ['achievementsOptOut'],
        ],
    })),
    actions({
        recordVisit: true,
    }),
    reducers({
        hasObservedLoading: [
            false,
            {
                collectionNodeLoadData: () => true,
            },
        ],
    }),
    sharedListeners(({ cache, values }) => ({
        maybeCaptureLoaded: () => {
            if (values.areAnyLoading || !values.hasObservedLoading || cache.hasCapturedLoaded) {
                return
            }
            cache.hasCapturedLoaded = true
            posthog.capture('web_analytics_dashboard_loaded', {
                duration_ms: Math.round(performance.now() - cache.mountStart),
                tile_skeletons_enabled: true,
            })
        },
    })),
    listeners(({ sharedListeners, cache, values }) => ({
        collectionNodeLoadDataSuccess: sharedListeners.maybeCaptureLoaded,
        collectionNodeLoadDataFailure: sharedListeners.maybeCaptureLoaded,
        recordVisit: async () => {
            if (
                cache.recordedVisitThisSession ||
                !isWebAnalyticsAchievementsEnabled(values.featureFlags, values.achievementsOptOut)
            ) {
                return
            }
            const projectId = values.currentProjectId
            if (projectId === undefined || projectId === null) {
                return
            }
            cache.recordedVisitThisSession = true
            try {
                await webAnalyticsAchievementsRecordVisit(String(projectId))
                webAnalyticsAchievementsLogic.findMounted()?.actions.loadAchievements()
            } catch {
                cache.recordedVisitThisSession = false
            }
        },
    })),
    afterMount(({ cache, actions }) => {
        cache.mountStart = performance.now()
        cache.hasCapturedLoaded = false
        posthog.capture('web_analytics_dashboard_mounted', {
            tile_skeletons_enabled: true,
        })
        actions.recordVisit()
    }),
])
