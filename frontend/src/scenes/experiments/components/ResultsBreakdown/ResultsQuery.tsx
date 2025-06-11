import { Query } from '~/queries/Query/Query'
import type { InsightVizNode } from '~/queries/schema/schema-general'
import type { FunnelStep, InsightShortId, TrendResult } from '~/types'

/**
 * shows a breakdown of the results for ExperimentFunnelsQueryResponse
 */
export const ResultsQuery = ({
    query,
    results,
}: {
    query: InsightVizNode
    results: FunnelStep[] | FunnelStep[][] | TrendResult[]
}): JSX.Element | null => {
    if (!query || !results) {
        return null
    }

    const fakeInsightId = Math.random().toString(36).substring(2, 15)

    return (
        <Query
            query={query}
            context={{
                insightProps: {
                    dashboardItemId: fakeInsightId as InsightShortId,
                    cachedInsight: {
                        short_id: fakeInsightId as InsightShortId,
                        query,
                        result: results,
                        disable_baseline: true,
                    },
                    doNotLoad: true,
                },
            }}
            readOnly
        />
    )
}
