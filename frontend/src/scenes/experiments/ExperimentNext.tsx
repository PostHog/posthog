import './Experiment.scss'

import { useActions, useValues } from 'kea'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    DistributionTable,
    ExperimentActiveBanner,
    ExperimentDraftBanner,
    ExperimentExposureModal,
    ExperimentGoal,
    ExperimentGoalModal,
    ExperimentLoader,
    ExperimentLoadingAnimation,
    ExperimentProgressBar,
    ExperimentStatus,
    ExperimentStoppedBanner,
    NoResultsEmptyState,
    PageHeaderCustom,
    ReleaseConditionsTable,
    Results,
    SecondaryMetricsTable,
} from './ExperimentResultsViz'

export function ExperimentView(): JSX.Element {
    const {
        experiment,
        isExperimentRunning,
        isExperimentStopped,
        experimentLoading,
        experimentResultsLoading,
        experimentId,
        experimentResults,
    } = useValues(experimentLogic)

    const { updateExperimentSecondaryMetrics } = useActions(experimentLogic)

    return (
        <>
            <PageHeaderCustom />
            <div className="space-y-8 experiment-view">
                {experimentLoading ? (
                    <ExperimentLoader />
                ) : (
                    <>
                        {isExperimentStopped ? (
                            <ExperimentStoppedBanner />
                        ) : isExperimentRunning ? (
                            <ExperimentActiveBanner />
                        ) : (
                            <ExperimentDraftBanner />
                        )}
                        {experimentResultsLoading ? (
                            <ExperimentLoadingAnimation />
                        ) : experimentResults && experimentResults.insight ? (
                            <>
                                <ExperimentStatus />
                                <ExperimentProgressBar />
                                <ExperimentGoal />
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
                                <ExperimentGoal />
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
