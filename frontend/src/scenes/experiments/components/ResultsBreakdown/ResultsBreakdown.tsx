import { BindLogic } from 'kea'

import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import { ExperimentMetricType, NodeKind } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ResultsBreakdownContent } from './ResultsBreakdownContent'
import { resultsBreakdownLogic } from './resultsBreakdownLogic'

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
        <BindLogic logic={resultsBreakdownLogic} props={{ experiment, metric: result.metric }}>
            <ResultsBreakdownContent />
        </BindLogic>
    )
}
