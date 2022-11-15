import { isLegacyQuery, isSavedInsight, LegacyQuery, Node, SavedInsightNode } from './nodes'
import { BindLogic } from 'kea'
import { insightLogic } from 'scenes/insights/insightLogic'
import { InsightLogicProps, ItemMode } from '~/types'
import { InsightContainer } from 'scenes/insights/InsightContainer'

export interface PostHogQueryProps {
    query: Node
}
export function PostHogQuery({ query }: PostHogQueryProps): JSX.Element {
    if (isLegacyQuery(query)) {
        return <LegacyInsightQuery query={query} />
    } else if (isSavedInsight(query)) {
        return <SavedInsightQuery query={query} />
    }

    return <div />
}

export function LegacyInsightQuery({ query }: { query: LegacyQuery }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: 'new', cachedInsight: { filters: query.filters } }
    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightContainer insightMode={ItemMode.View} />
        </BindLogic>
    )
}

export function SavedInsightQuery({ query }: { query: SavedInsightNode }): JSX.Element {
    const insightProps: InsightLogicProps = { dashboardItemId: query.shortId }
    return (
        <BindLogic logic={insightLogic} props={insightProps}>
            <InsightContainer insightMode={ItemMode.View} />
        </BindLogic>
    )
}
