import './Experiment.scss'

import { useActions, useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    DistributionTable,
    EllipsisAnimation,
    ExperimentActiveBanner,
    ExperimentDraftBanner,
    ExperimentExposureModal,
    ExperimentGoalModal,
    ExperimentLoader,
    ExperimentProgressBar,
    ExperimentStatus,
    ExperimentStoppedBanner,
    NoResultsEmptyState,
    QueryViz,
    ReleaseConditionsTable,
    SecondaryMetricsTable,
    SummaryTable,
} from './ExperimentResultsViz'

export function ExperimentResults(): JSX.Element {
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
                </>
            )}

            <>
                {!experimentLoading && (
                    <>
                        {experimentResultsLoading ? (
                            <div className="flex flex-col flex-1 justify-center items-center">
                                <Animation type={AnimationType.LaptopHog} />
                                <div className="text-xs text-muted w-44">
                                    <span className="mr-1">Fetching experiment results</span>
                                    <EllipsisAnimation />
                                </div>
                            </div>
                        ) : experimentResults && experimentResults.insight ? (
                            <>
                                <ExperimentStatus />
                                <ExperimentProgressBar />
                                <SummaryTable />
                                <QueryViz />
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
                                <ExperimentImplementationDetails experiment={experiment} />
                                {experiment.start_date && <NoResultsEmptyState />}
                            </>
                        )}
                    </>
                )}
            </>

            {!experimentLoading && (
                <>
                    <DistributionTable />
                    <ReleaseConditionsTable />
                </>
            )}
        </div>
    )
}

export function ExperimentNext(): JSX.Element {
    const { experimentId, editingExistingExperiment } = useValues(experimentLogic)

    return experimentId === 'new' || editingExistingExperiment ? <ExperimentForm /> : <ExperimentResults />
}
