import './Experiment.scss'

import { useActions, useValues } from 'kea'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import { ExperimentLoader, ExperimentLoadingAnimation, PageHeaderCustom } from './ExperimentView/components'
import { DistributionTable } from './ExperimentView/DistributionTable'
import { ExperimentExposureModal, ExperimentGoalModal, Goal } from './ExperimentView/Goal'
import { Info } from './ExperimentView/Info'
import { NoResultsEmptyState } from './ExperimentView/NoResultsEmptyState'
import { Overview } from './ExperimentView/Overview'
import { ProgressBar } from './ExperimentView/ProgressBar'
import { ReleaseConditionsTable } from './ExperimentView/ReleaseConditionsTable'
import { Results } from './ExperimentView/Results'
import { SecondaryMetricsTable } from './ExperimentView/SecondaryMetricsTable'

export function ExperimentView(): JSX.Element {
    const { experiment, experimentLoading, experimentResultsLoading, experimentId, experimentResults } =
        useValues(experimentLogic)

    const { updateExperimentSecondaryMetrics } = useActions(experimentLogic)

    return (
        <>
            <PageHeaderCustom />
            <div className="space-y-8 experiment-view">
                {experimentLoading ? (
                    <ExperimentLoader />
                ) : (
                    <>
                        <Info />
                        {experimentResultsLoading ? (
                            <ExperimentLoadingAnimation />
                        ) : experimentResults && experimentResults.insight ? (
                            <>
                                <Overview />
                                <ProgressBar />
                                <Goal />
                                <Results />
                                <SecondaryMetricsTable
                                    experimentId={experiment.id}
                                    onMetricsChange={(metrics) => updateExperimentSecondaryMetrics(metrics)}
                                    initialMetrics={experiment.secondary_metrics}
                                    defaultAggregationType={experiment.parameters?.aggregation_group_type_index}
                                />
                                <ExperimentGoalModal experimentId={experimentId} />
                                <ExperimentExposureModal experimentId={experimentId} />
                            </>
                        ) : (
                            <>
                                <Goal />
                                <ExperimentImplementationDetails experiment={experiment} />
                                {experiment.start_date && <NoResultsEmptyState />}
                            </>
                        )}
                        <DistributionTable />
                        <ReleaseConditionsTable />
                    </>
                )}
            </div>
        </>
    )
}

export function ExperimentNext(): JSX.Element {
    const { experimentId, editingExistingExperiment } = useValues(experimentLogic)

    return experimentId === 'new' || editingExistingExperiment ? <ExperimentForm /> : <ExperimentView />
}
