import clsx from 'clsx'
import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { FEATURE_FLAGS } from 'lib/constants'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { LemonSkeleton } from 'lib/lemon-ui/LemonSkeleton'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightModals } from 'scenes/insights/InsightModals'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isDataVisualizationNode, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ItemMode } from '~/types'

import { teamLogic } from '../teamLogic'
import { InsightRetentionBanner } from './dataRetention/InsightRetentionBanner'
import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'
import { InsightSceneHeader } from './InsightSceneHeader'
import { insightVizDataLogic } from './insightVizDataLogic'

export interface InsightAsSceneProps {
    insightId: InsightShortId | 'new'
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

export function InsightAsScene({ insightId, attachTo }: InsightAsSceneProps): JSX.Element | null {
    // insightSceneLogic
    const { insightMode, insight, filtersOverride, variablesOverride, hasOverrides, dashboardId } =
        useValues(insightSceneLogic)
    const { currentTeamId } = useValues(teamLogic)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || 'new',
        dashboardId: dashboardId ?? undefined,
        // don't use cached insight if we have overrides
        cachedInsight: hasOverrides && insight?.short_id === insightId ? insight : null,
        filtersOverride,
        variablesOverride,
    })
    const { insightProps, accessDeniedToInsight, insightLoading } = useValues(logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const dragToZoomEnabled = !!featureFlags[FEATURE_FLAGS.INSIGHT_DRAG_TO_ZOOM]

    // insightDataLogic
    const { query, showQueryEditor } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))
    const { zoomDateRange } = useActions(insightVizDataLogic(insightProps))

    useFileSystemLogView({
        type: 'insight',
        ref: insight?.short_id,
        enabled: Boolean(currentTeamId && insight?.short_id && insight?.saved && !accessDeniedToInsight),
    })

    // other logics
    useAttachedLogic(logic, attachTo) // insightLogic(insightProps)
    useAttachedLogic(insightDataLogic(insightProps), attachTo)

    const actuallyShowQueryEditor = insightMode === ItemMode.Edit && showQueryEditor

    const setQuery = (q: Node | ((q: Node) => Node), isSourceUpdate?: boolean): void => {
        let node = typeof q === 'function' ? (query ? q(query) : null) : q
        if (!isInsightVizNode(node) || isSourceUpdate) {
            setInsightQuery(node)
        }
    }

    if (accessDeniedToInsight) {
        return <AccessDenied object="insight" />
    }

    if (!insight?.query) {
        return null
    }

    const isEditing = insightMode === ItemMode.Edit

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightModals insightLogicProps={insightProps} />
            <SceneContent className={clsx('Insight', isEditing && '!gap-0')}>
                {isEditing ? (
                    <div className="flex flex-col gap-y-4 shrink-0">
                        <InsightSceneHeader insightLogicProps={insightProps} />
                    </div>
                ) : (
                    <InsightSceneHeader insightLogicProps={insightProps} />
                )}

                <InsightRetentionBanner insightProps={insightProps} />

                {isDataVisualizationNode(query) && insightLoading ? (
                    // Avoid painting the stale chart type during a reload (the query re-syncs in insightDataLogic).
                    <LemonSkeleton className="h-100 w-full" />
                ) : (
                    <Query
                        attachTo={attachTo}
                        query={isInsightVizNode(query) ? { ...query, full: true } : query}
                        setQuery={setQuery}
                        readOnly={insightMode !== ItemMode.Edit}
                        editMode={insightMode === ItemMode.Edit}
                        context={{
                            showOpenEditorButton: false,
                            showQueryEditor: actuallyShowQueryEditor,
                            showQueryHelp: insightMode === ItemMode.Edit && !containsHogQLQuery(query),
                            insightProps,
                            onDateRangeZoom: dragToZoomEnabled ? zoomDateRange : undefined,
                        }}
                        filtersOverride={filtersOverride}
                        variablesOverride={variablesOverride}
                    />
                )}
            </SceneContent>
        </BindLogic>
    )
}
