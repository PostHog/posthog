import './Experiment.scss'

import { useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    DistributionTable,
    ExperimentActiveBanner,
    ExperimentDraftBanner,
    ExperimentExposureModal,
    ExperimentGoalModal,
    ExperimentProgressBar,
    ExperimentStatus,
    ExperimentStoppedBanner,
    NoResultsEmptyState,
    QueryViz,
    ReleaseConditionsTable,
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

    if (experimentLoading || experimentResultsLoading) {
        return (
            <div className="flex flex-col flex-1 justify-center items-center">
                <Animation type={AnimationType.LaptopHog} />
            </div>
        )
    }

    return (
        <div className="space-y-8 experiment-results">
            {isExperimentStopped ? (
                <ExperimentStoppedBanner />
            ) : isExperimentRunning ? (
                <ExperimentActiveBanner />
            ) : (
                <ExperimentDraftBanner />
            )}
            {experimentResults && experimentResults.insight ? (
                <>
                    <ExperimentStatus />
                    <ExperimentProgressBar />
                    <SummaryTable />
                    <QueryViz />
                    <DistributionTable />
                    <ReleaseConditionsTable />

                    <ExperimentGoalModal experimentId={experimentId} />
                    <ExperimentExposureModal experimentId={experimentId} />
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
