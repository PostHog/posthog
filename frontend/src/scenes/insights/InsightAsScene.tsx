import { BindLogic, BuiltLogic, Logic, LogicWrapper, useActions, useValues } from 'kea'

import { AccessDenied } from 'lib/components/AccessDenied'
import { useFileSystemLogView } from 'lib/hooks/useFileSystemLogView'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { InsightModals } from 'scenes/insights/InsightModals'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema/schema-general'
import { containsHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ItemMode } from '~/types'

import { teamLogic } from '../teamLogic'
import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'
import { InsightSceneHeader } from './InsightSceneHeader'

export interface InsightAsSceneProps {
    insightId: InsightShortId | 'new'
    tabId: string
    attachTo?: BuiltLogic<Logic> | LogicWrapper<Logic>
}

export function InsightAsScene({ insightId, attachTo, tabId }: InsightAsSceneProps): JSX.Element | null {
    // insightSceneLogic
    const { insightMode, insight, filtersOverride, variablesOverride, hasOverrides, dashboardId } =
        useValues(insightSceneLogic)
    const { currentTeamId } = useValues(teamLogic)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || `new-${tabId}`,
        dashboardId: dashboardId ?? undefined,
        tabId,
        // don't use cached insight if we have overrides
        cachedInsight: hasOverrides && insight?.short_id === insightId ? insight : null,
        filtersOverride,
        variablesOverride,
    })
    const { insightProps, accessDeniedToInsight } = useValues(logic)

    // insightDataLogic
    const { query, showQueryEditor } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))

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

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightModals insightLogicProps={insightProps} />
            <SceneContent className="Insight">
                <InsightSceneHeader insightLogicProps={insightProps} />

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
