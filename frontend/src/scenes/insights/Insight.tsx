import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { DebugCHQueries } from 'lib/components/CommandPalette/DebugCHQueries'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'

import { Query } from '~/queries/Query/Query'
import { Node } from '~/queries/schema'
import { containsHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { InsightShortId, ItemMode } from '~/types'

import { insightCommandLogic } from './insightCommandLogic'
import { insightDataLogic } from './insightDataLogic'
import { insightLogic } from './insightLogic'
import { InsightsNav } from './InsightNav/InsightsNav'
export interface InsightSceneProps {
    insightId: InsightShortId | 'new'
}

export function Insight({ insightId }: InsightSceneProps): JSX.Element {
    // insightSceneLogic
    const { insightMode, insight } = useValues(insightSceneLogic)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || 'new',
        cachedInsight: insight?.short_id === insightId ? insight : null,
    })
    const { insightProps } = useValues(logic)

    // insightDataLogic
    const { query, showQueryEditor, showDebugPanel } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))

    const actuallyShowQueryEditor = insightMode === ItemMode.Edit && showQueryEditor

    const setQuery = (query: Node, isSourceUpdate?: boolean): void => {
        if (!isInsightVizNode(query) || isSourceUpdate) {
            setInsightQuery(query)
        }
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className="Insight">
                <InsightPageHeader insightLogicProps={insightProps} />

                {insightMode === ItemMode.Edit && <InsightsNav />}

                {showDebugPanel && (
                    <div className="mb-4">
                        <DebugCHQueries insightId={insightProps.cachedInsight?.id} />
                    </div>
                )}

                <Query
                    query={isInsightVizNode(query) ? { ...query, full: true } : query}
                    setQuery={insightMode === ItemMode.Edit ? setQuery : undefined}
                    readOnly={insightMode !== ItemMode.Edit}
                    context={{
                        showOpenEditorButton: false,
                        showQueryEditor: actuallyShowQueryEditor,
                        showQueryHelp: insightMode === ItemMode.Edit && !containsHogQLQuery(query),
                        insightProps,
                    }}
                />
            </div>
        </BindLogic>
    )
}
