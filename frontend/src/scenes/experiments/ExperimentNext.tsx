import './Experiment.scss'

import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'

import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    ExperimentLoader,
    ExperimentLoadingAnimation,
    NoResultsEmptyState,
    PageHeaderCustom,
} from './ExperimentView/components'
import { DistributionTable } from './ExperimentView/DistributionTable'
import { ExperimentExposureModal, ExperimentGoalModal, Goal } from './ExperimentView/Goal'
import { Info } from './ExperimentView/Info'
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
                                <div>
                                    <Overview />
                                    <LemonDivider className="mt-4" />
                                </div>
                                <div className="xl:flex">
                                    <div className="w-1/2 pr-2">
                                        <Goal />
                                    </div>

                                    <div className="w-1/2 xl:pl-2 mt-8 xl:mt-0">
                                        <ProgressBar />
                                    </div>
                                </div>
                                <Results />
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
                        <SecondaryMetricsTable
                            experimentId={experiment.id}
                            onMetricsChange={(metrics) => updateExperimentSecondaryMetrics(metrics)}
                            initialMetrics={experiment.secondary_metrics}
                            defaultAggregationType={experiment.parameters?.aggregation_group_type_index}
                        />
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
