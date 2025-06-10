import { useValues } from 'kea'

import { Query } from '~/queries/Query/Query'
import { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { Experiment, InsightShortId } from '~/types'

import { resultsBreakdownLogic } from './resultsBreakdownLogic'

/**
 * shows a breakdown of the results for ExperimentFunnelsQueryResponse
 */
export const ResultsQuery = ({
    result,
    experiment,
}: {
    result: CachedExperimentQueryResponse
    experiment: Experiment
}): JSX.Element | null => {
    /**
     * we get the generated query and the results from the breakdown logic
     */
    const { breakdownResults, query } = useValues(resultsBreakdownLogic({ experiment, metric: result.metric }))

    if (!breakdownResults) {
        return null
    }

    const { results } = breakdownResults

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
