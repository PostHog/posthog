import './Experiment.scss'

import { LemonBanner } from '@posthog/lemon-ui'
import { useValues } from 'kea'
import { AnimationType } from 'lib/animations/animations'
import { Animation } from 'lib/components/Animation/Animation'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    DistributionTable,
    ExperimentExposureModal,
    ExperimentGoalModal,
    ExperimentProgressBar,
    ExperimentStatus,
    NoResultsEmptyState,
    QueryViz,
    ReleaseConditionsTable,
    SummaryTable,
} from './ExperimentResultsViz'

export function ExperimentResults(): JSX.Element {
    const { experiment, isDraft, experimentLoading, experimentResultsLoading, experimentId, experimentResults } =
        useValues(experimentLogic)

    if (experimentLoading || experimentResultsLoading) {
        return (
            <div className="flex flex-col flex-1 justify-center items-center">
                <Animation type={AnimationType.LaptopHog} />
            </div>
        )
    }

    return (
        <div className="space-y-8 experiment-results">
            {isDraft ? (
                <LemonBanner type="info">
                    This experiment is a <b>draft</b>.
                </LemonBanner>
            ) : (
                <LemonBanner type="info">
                    This experiment is <b>active</b>.
                </LemonBanner>
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
