import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useMountedLogic, useValues } from 'kea'

import { LemonBanner, LemonButton } from '@posthog/lemon-ui'

import { AccessDenied } from 'lib/components/AccessDenied'
import { DebugCHQueries } from 'lib/components/CommandPalette/DebugCHQueries'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { ReloadInsight } from 'scenes/saved-insights/ReloadInsight'
import { urls } from 'scenes/urls'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ItemMode } from '~/types'

import { teamLogic } from '../teamLogic'
import { InsightsNav } from './InsightNav/InsightsNav'
import { insightCommandLogic } from './insightCommandLogic'
import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'

export interface InsightAsSceneProps {
    insightId: InsightShortId | 'new'
    tabId: string
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

export function InsightAsScene({ insightId, attachTo, tabId }: InsightAsSceneProps): JSX.Element | null {
    // insightSceneLogic
    const { insightMode, insight, filtersOverride, variablesOverride, hasOverrides, freshQuery } =
        useValues(insightSceneLogic)
    const { currentTeamId } = useValues(teamLogic)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || `new-${tabId}`,
        tabId,
        // don't use cached insight if we have overrides
        cachedInsight: hasOverrides && insight?.short_id === insightId ? insight : null,
        filtersOverride,
        variablesOverride,
    })
    const { insightProps, accessDeniedToInsight } = useValues(logic)

    // insightDataLogic
    const { query, showQueryEditor, showDebugPanel } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))

    useFileSystemLogView({
        type: 'insight',
        ref: insight?.short_id,
        enabled: Boolean(currentTeamId && insight?.short_id && insight?.saved && !accessDeniedToInsight),
        deps: [currentTeamId, insight?.short_id, insight?.saved, accessDeniedToInsight],
    })

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))
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

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <SceneContent className="Insight">
                <InsightPageHeader insightLogicProps={insightProps} />

                {hasOverrides && (
                    <LemonBanner type="warning" className="mb-4">
                        <div className="flex flex-row items-center justify-between gap-2">
                            <span>
                                You are viewing this insight with filter/variable overrides. Discard them to edit the
                                insight.
                            </span>

                            <LemonButton type="secondary" to={urls.insightView(insightId as InsightShortId)}>
                                Discard overrides
                            </LemonButton>
                        </div>
                    </LemonBanner>
                )}

                {insightMode === ItemMode.Edit && <InsightsNav />}

                {showDebugPanel && (
                    <div className="mb-4">
                        <DebugCHQueries insightId={insightProps.cachedInsight?.id} />
                    </div>
                )}

                {freshQuery ? <ReloadInsight /> : null}

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
                    }}
                    filtersOverride={filtersOverride}
                    variablesOverride={variablesOverride}
                />
            </SceneContent>
        </BindLogic>
    )
}
