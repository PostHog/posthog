import { Query } from '~/queries/Query/Query'
import type {
    ExperimentFunnelsQueryResponse,
    ExperimentTrendsQueryResponse,
    InsightVizNode,
} from '~/queries/schema/schema-general'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'

/**
 * @deprecated
 * This component supports legacy experiment metrics (ExperimentTrendsQuery/ExperimentFunnelsQuery).
 * Frozen copy for legacy experiments - do not modify.
 */
export function LegacyResultsQuery({
    result,
    showTable,
}: {
    result: ExperimentTrendsQueryResponse | ExperimentFunnelsQueryResponse | null
    showTable: boolean
}): JSX.Element {
    if (!result) {
        return <></>
    }

    const query = result.kind === NodeKind.ExperimentTrendsQuery ? result.count_query : result.funnels_query

    const fakeInsightId = Math.random().toString(36).substring(2, 15)

    return (
        <Query
            query={{
                kind: NodeKind.InsightVizNode,
                source: query,
                showTable,
                showLastComputation: true,
                showLastComputationRefresh: false,
            }}
            context={{
                insightProps: {
                    dashboardItemId: fakeInsightId as InsightShortId,
                    cachedInsight: {
                        short_id: fakeInsightId as InsightShortId,
                        query: {
                            kind: NodeKind.InsightVizNode,
                            source: query,
                        } as InsightVizNode,
                        result: result?.insight,
                        disable_baseline: true,
                    },
                    doNotLoad: true,
                },
            }}
            readOnly
        />
    )
}
