import { useActions, useValues } from 'kea'

import { LiveUserCount } from 'lib/components/LiveUserCount'
import { FEATURE_FLAGS } from 'lib/constants'
import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { ActivitySceneHeader } from 'scenes/activity/ActivitySceneHeader'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from 'scenes/feature-flags/flagEvaluationsTable'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'
import { LiveRecordingsCount } from 'scenes/session-recordings/components/LiveRecordingsCount'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { QueryFeature } from '~/queries/nodes/DataTable/queryFeatures'
import { Query } from '~/queries/Query/Query'
import { isDataTableNode } from '~/queries/schema/node-guards'
import { DataTableNode, ProductKey } from '~/queries/schema/schema-general'
import { isEventsQuery } from '~/queries/utils'
import { ActivityTab } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { buildExploreAgentContext } from '../activityAgentContext'
import { widerActivityRange } from './defaults'
import { eventsSceneLogic } from './eventsSceneLogic'
import { SAMPLE_EVENTS_SOURCE } from './sampleEventRows'

export function EventsScene(): JSX.Element {
    const { query, flagCallsNote } = useValues(eventsSceneLogic())
    const { setQuery } = useActions(eventsSceneLogic())
    const { featureFlags } = useValues(featureFlagLogic)

    const dataTableQuery = isDataTableNode(query) ? query : null
    const eventsSource = dataTableQuery && isEventsQuery(dataTableQuery.source) ? dataTableQuery.source : null
    const widerRange = eventsSource ? widerActivityRange(eventsSource.after, eventsSource.before) : null
    const widerQuery: DataTableNode | null =
        dataTableQuery && eventsSource && widerRange
            ? { ...dataTableQuery, source: { ...eventsSource, after: widerRange.after } }
            : null

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
                    dataTableSampleRows: SAMPLE_EVENTS_SOURCE,
                    // The scene defaults to the last hour, so an empty list is often a narrow window,
                    // not missing data. Offer the next wider range in one click.
                    emptyStateDetail:
                        widerQuery && widerRange ? (
                            <div className="flex flex-col items-center gap-2">
                                <span>Try changing the date range, or pick another action, event or breakdown.</span>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    data-attr="events-empty-widen-date-range"
                                    onClick={() => setQuery(widerQuery)}
                                >
                                    {widerRange.label}
                                </LemonButton>
                            </div>
                        ) : undefined,
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
