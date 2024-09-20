import { LemonBanner, LemonButton } from '@posthog/lemon-ui'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { DebugCHQueries } from 'lib/components/CommandPalette/DebugCHQueries'
import { isObject } from 'lib/utils'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { urls } from 'scenes/urls'

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
    const { insightMode, insight, filtersOverride } = useValues(insightSceneLogic)

    // insightLogic
    const logic = insightLogic({
        dashboardItemId: insightId || 'new',
        // don't use cached insight if we have filtersOverride
        cachedInsight: isObject(filtersOverride) && insight?.short_id === insightId ? insight : null,
        filtersOverride,
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

                {isObject(filtersOverride) && (
                    <LemonBanner type="warning" className="mb-4">
                        <div className="flex flex-row items-center justify-between gap-2">
                            <span>You are viewing this insight with filters from a dashboard</span>

                            <LemonButton type="secondary" to={urls.insightView(insightId as InsightShortId)}>
                                Discard dashboard filters
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
                    filtersOverride={filtersOverride}
                />
            </div>
        </BindLogic>
    )
}
