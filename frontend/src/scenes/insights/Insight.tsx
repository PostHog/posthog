import './Insight.scss'
import { useEffect } from 'react'
import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { insightSceneLogic } from 'scenes/insights/insightSceneLogic'
import { insightLogic } from './insightLogic'
import { insightCommandLogic } from './insightCommandLogic'
import { insightDataLogic } from './insightDataLogic'
import { InsightShortId, ItemMode } from '~/types'
import { InsightsNav } from './InsightNav/InsightsNav'
import { InsightSkeleton } from 'scenes/insights/InsightSkeleton'
import { Query } from '~/queries/Query/Query'
import { InsightPageHeader } from 'scenes/insights/InsightPageHeader'
import { containsHogQLQuery, isInsightVizNode } from '~/queries/utils'
import { Node } from '~/queries/schema'
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
    const { insightProps, insightLoading, filtersKnown } = useValues(logic)
    const { reportInsightViewedForRecentInsights } = useActions(logic)

    // insightDataLogic
    const { query, isQueryBasedInsight, showQueryEditor } = useValues(insightDataLogic(insightProps))
    const { setQuery: setInsightQuery } = useActions(insightDataLogic(insightProps))

    // other logics
    useMountedLogic(insightCommandLogic(insightProps))

    useEffect(() => {
        reportInsightViewedForRecentInsights()
    }, [insightId])

    // Show the skeleton if loading an insight for which we only know the id
    // This helps with the UX flickering and showing placeholder "name" text.
    if (insightId !== 'new' && insightLoading && !filtersKnown) {
        return <InsightSkeleton />
    }

    const actuallyShowQueryEditor =
        insightMode === ItemMode.Edit &&
        ((isQueryBasedInsight && !containsHogQLQuery(query)) || (!isQueryBasedInsight && showQueryEditor))

    const setQuery = (query: Node): void => {
        if (!isInsightVizNode(query)) {
            setInsightQuery(query)
        }
    }

    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <div className={'insights-page'}>
                <InsightPageHeader insightLogicProps={insightProps} />

                {insightMode === ItemMode.Edit && <InsightsNav />}

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
