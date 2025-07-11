import { BindLogic } from 'kea'

import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import type { Experiment } from '~/types'

import { ResultsBreakdownContent } from './ResultsBreakdownContent'
import { resultsBreakdownLogic } from './resultsBreakdownLogic'
import type { ResultBreakdownRenderProps } from './types'

export const ResultsBreakdown = ({
    result,
    experiment,
    metricIndex,
    isPrimary,
    children,
}: {
    result: CachedExperimentQueryResponse
    experiment: Experiment
    metricIndex: number
    isPrimary: boolean
    children?: (props: ResultBreakdownRenderProps) => JSX.Element | null
}): JSX.Element | null => {
    return (
        <BindLogic logic={resultsBreakdownLogic} props={{ experiment, metric: result.metric, metricIndex, isPrimary }}>
            <ResultsBreakdownContent result={result}>{children}</ResultsBreakdownContent>
        </BindLogic>
    )
}
