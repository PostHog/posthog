import { BindLogic } from 'kea'

import type { CachedExperimentQueryResponse, InsightVizNode } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment, FunnelStep, TrendResult } from '~/types'

import { ResultsBreakdownContent } from './ResultsBreakdownContent'
import { resultsBreakdownLogic } from './resultsBreakdownLogic'

export const ResultsBreakdown = ({
    result,
    experiment,
    children,
}: {
    result: CachedExperimentQueryResponse
    experiment: Experiment
    children?: (query: InsightVizNode, results: FunnelStep[] | FunnelStep[][] | TrendResult[]) => JSX.Element
}): JSX.Element | null => {
    /**
     * bail if the result is not from an experiment funnel metric.
     */
    if (result.kind !== NodeKind.ExperimentQuery || result.metric?.metric_type !== ExperimentMetricType.FUNNEL) {
        return null
    }

    return (
        <BindLogic logic={resultsBreakdownLogic} props={{ experiment, metric: result.metric }}>
            <ResultsBreakdownContent>{children}</ResultsBreakdownContent>
        </BindLogic>
    )
}
