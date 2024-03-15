import './Experiment.scss'

import { useValues } from 'kea'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    DistributionTable,
    ExperimentProgressBar,
    NoResultsEmptyState,
    QueryViz,
    ReleaseConditionsTable,
    SummaryTable,
} from './ExperimentResultsViz'

interface ExperimentResultProps {
    secondaryMetricId?: number
}
export function ExperimentResults({ secondaryMetricId }: ExperimentResultProps): JSX.Element {
    const { experiment, experimentResults, secondaryMetricResults } = useValues(experimentLogic)

    const isSecondaryMetric = secondaryMetricId !== undefined
    const targetResults = isSecondaryMetric ? secondaryMetricResults?.[secondaryMetricId] : experimentResults

    const validMetric = targetResults && targetResults.insight

    return (
        <div className="space-y-6">
            {validMetric ? (
                <>
                    <h2>Experiment results</h2>
                    <ExperimentProgressBar />
                    <SummaryTable />
                    <QueryViz />
                    <DistributionTable />
                    <ReleaseConditionsTable />
                </>
            ) : (
                <>
                    <h2>Experiment draft/no results yet</h2>
                    <ExperimentImplementationDetails experiment={experiment} />
                    <NoResultsEmptyState />
                </>
            )}
        </div>
    )
}

export function ExperimentNext(): JSX.Element {
    const { experimentId, editingExistingExperiment } = useValues(experimentLogic)

    return experimentId === 'new' || editingExistingExperiment ? <ExperimentForm /> : <ExperimentResults />
}
