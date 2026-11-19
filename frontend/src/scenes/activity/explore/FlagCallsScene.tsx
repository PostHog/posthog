import { useActions, useValues } from 'kea'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { ActivitySceneHeader } from 'scenes/activity/ActivitySceneHeader'
import { FLAG_EVALUATIONS_RETENTION_DAYS } from 'scenes/feature-flags/flagEvaluationsTable'
import { sceneConfigurations } from 'scenes/scenes'
import { Scene, SceneExport } from 'scenes/sceneTypes'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { DataTableNode, ProductKey } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { useAttachedContext } from 'products/posthog_ai/frontend/api/logics'

import { buildExploreAgentContext } from '../activityAgentContext'
import { widerActivityRange } from './defaults'
import { flagCallsSceneLogic } from './flagCallsSceneLogic'

export function FlagCallsScene(): JSX.Element {
    const { query, reachesPastRetention } = useValues(flagCallsSceneLogic())
    const { setQuery } = useActions(flagCallsSceneLogic())

    const widerRange = widerActivityRange(query.source.after, query.source.before)
    const widerQuery: DataTableNode | null = widerRange
        ? { ...query, source: { ...query.source, after: widerRange.after } }
        : null

    useAttachedContext(buildExploreAgentContext(ActivityTab.ExploreFlagCalls, query))

    return (
        <SceneContent>
            <ActivitySceneHeader
                activeKey={ActivityTab.ExploreFlagCalls}
                name={sceneConfigurations[Scene.ExploreFlagCalls].name}
                description={sceneConfigurations[Scene.ExploreFlagCalls].description}
                iconType={sceneConfigurations[Scene.ExploreFlagCalls].iconType}
            />
            {reachesPastRetention && (
                <LemonBanner type="info">
                    This list shows feature flag calls from the last {FLAG_EVALUATIONS_RETENTION_DAYS} days.
                </LemonBanner>
            )}
            <Query
                attachTo={flagCallsSceneLogic()}
                uniqueKey="flag-calls-scene"
                query={query}
                setQuery={setQuery}
                context={{
                    showOpenEditorButton: true,
                    dataTableMaxPaginationLimit: 200,
                    emptyStateDetail:
                        widerQuery && widerRange ? (
                            <div className="flex flex-col items-center gap-2">
                                <span>Try changing the date range or filters.</span>
                                <LemonButton
                                    type="secondary"
                                    size="small"
                                    data-attr="flag-calls-empty-widen-date-range"
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
    component: FlagCallsScene,
    logic: flagCallsSceneLogic,
    productKey: ProductKey.FEATURE_FLAGS,
}
