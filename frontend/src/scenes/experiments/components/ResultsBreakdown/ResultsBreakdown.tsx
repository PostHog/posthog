import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ExploreAsInsightButton } from './ExploreAsInsightButton'
import { ResultsQuery } from './ResultsQuery'

export const ResultsBreakdown = ({
    result,
    experiment,
}: {
    result: CachedExperimentQueryResponse
    experiment: Experiment
}): JSX.Element | null => {
    /**
     * bail if the result is not from an experiment funnel metric.
     */
    if (result.kind !== NodeKind.ExperimentQuery || result.metric?.metric_type !== ExperimentMetricType.FUNNEL) {
        return null
    }

    return (
        <div>
            <div className="flex justify-end">
                <ExploreAsInsightButton result={result} size="xsmall" />
            </div>
            <div className="pb-4">
                <ResultsQuery experiment={experiment} result={result} />
            </div>
        </div>
    )
}
