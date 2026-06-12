import { afterMount, connect, kea, listeners, path, reducers, selectors, sharedListeners } from 'kea'
import posthog from 'posthog-js'

import { FEATURE_FLAGS } from 'lib/constants'
import { FeatureFlagsSet, featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { dataNodeCollectionLogic } from '~/queries/nodes/DataNode/dataNodeCollectionLogic'

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
        ],
    })),
    reducers({
        hasObservedLoading: [
            false,
            {
                collectionNodeLoadData: () => true,
            },
        ],
    }),
    selectors({
        tileSkeletonsEnabled: [
            (s) => [s.featureFlags],
            (flags: FeatureFlagsSet): boolean => !!flags[FEATURE_FLAGS.WEB_ANALYTICS_TILE_SKELETONS],
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
                tile_skeletons_enabled: values.tileSkeletonsEnabled,
            })
        },
    })),
    listeners(({ sharedListeners }) => ({
        collectionNodeLoadDataSuccess: sharedListeners.maybeCaptureLoaded,
        collectionNodeLoadDataFailure: sharedListeners.maybeCaptureLoaded,
    })),
    afterMount(({ cache, values }) => {
        cache.mountStart = performance.now()
        cache.hasCapturedLoaded = false
        posthog.capture('web_analytics_dashboard_mounted', {
            tile_skeletons_enabled: values.tileSkeletonsEnabled,
        })
    }),
])
