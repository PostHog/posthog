import { useActions, useValues } from 'kea'

import { LiveUserCount } from 'lib/components/LiveUserCount'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ActivitySceneHeader } from 'scenes/activity/ActivitySceneHeader'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from 'scenes/feature-flags/featureFlagUsageQueries'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { LiveRecordingsCount } from 'scenes/session-recordings/components/LiveRecordingsCount'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { buildExploreAgentContext } from '../activityAgentContext'
import { eventsSceneLogic } from './eventsSceneLogic'

export function EventsScene(): JSX.Element {
    const { query, flagCallsNote } = useValues(eventsSceneLogic())
    const { setQuery } = useActions(eventsSceneLogic())
    const { featureFlags } = useValues(featureFlagLogic)

    useAttachedContext(buildExploreAgentContext(ActivityTab.ExploreEvents, query))

    return (
        <SceneContent>
            <ActivitySceneHeader
                activeKey={ActivityTab.ExploreEvents}
                name={sceneConfigurations[Scene.Activity].name}
                description={sceneConfigurations[Scene.Activity].description}
                iconType={sceneConfigurations[Scene.ExploreEvents].iconType}
            />
            {featureFlags[FEATURE_FLAGS.LIVESTREAM_HOGQL] && (
                <div className="flex flex-wrap gap-2 mb-2">
                    <LiveUserCount />
                    <LiveRecordingsCount />
                </div>
            )}
            {flagCallsNote === 'stored-separately' && (
                <LemonBanner type="info" dismissKey="activity-flag-calls-stored-separately">
                    Feature flag calls are stored separately from other events. Filter by only the "Feature flag called"
                    event to see them.
                </LemonBanner>
            )}
            {flagCallsNote === 'retention' && (
                <LemonBanner type="info">
                    This list shows feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days.
                </LemonBanner>
            )}
            <Query
                attachTo={eventsSceneLogic()}
                uniqueKey="events-scene"
                query={query}
                setQuery={setQuery}
                context={{
                    showOpenEditorButton: true,
                    extraDataTableQueryFeatures: [QueryFeature.highlightExceptionEventRows],
                    dataTableMaxPaginationLimit: 200,
                    // A live-data explorer over captured events, so it keeps the hidden ones selectable.
                    includeHiddenEvents: true,
                }}
            />
        </SceneContent>
    )
}

export const scene: SceneExport = {
    component: EventsScene,
    logic: eventsSceneLogic,
    productKey: ProductKey.PRODUCT_ANALYTICS,
}
