import { Query } from '~/queries/Query/Query'
import { NodeKind } from '~/queries/schema/schema-general'
import type { InsightShortId } from '~/types'

import type { ResultBreakdownRenderProps } from './types'

/**
 * make the props non-nullable except for breakdownLastRefresh which can be null
 */
type SafeResultBreakdownRenderProps = {
    [K in keyof Omit<
        ResultBreakdownRenderProps,
        'breakdownResultsLoading' | 'exposureDifference' | 'breakdownLastRefresh'
    >]: NonNullable<ResultBreakdownRenderProps[K]>
} & {
    breakdownLastRefresh: string | null
}

/**
 * shows a breakdown of the results for ExperimentFunnelsQueryResponse
 */
export const ResultsQuery = ({
    query,
    breakdownResults,
    breakdownLastRefresh,
}: SafeResultBreakdownRenderProps): JSX.Element | null => {
    /**
     * bail if the result is from a trends query.
     * trends queries are not supported yet.
     */
    if (query.source.kind === NodeKind.TrendsQuery) {
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
                        result: breakdownResults,
                        last_refresh: breakdownLastRefresh,
                        disable_baseline: true,
                    },
                    doNotLoad: true,
                },
            }}
            readOnly
        />
    )
}
