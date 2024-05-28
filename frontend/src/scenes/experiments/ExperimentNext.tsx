import './Experiment.scss'

import { LemonDivider } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { NotFound } from 'lib/components/NotFound'

import { LoadingState } from './Experiment'
import { ExperimentForm } from './ExperimentForm'
import { ExperimentImplementationDetails } from './ExperimentImplementationDetails'
import { experimentLogic } from './experimentLogic'
import {
    ExperimentLoadingAnimation,
    NoResultsEmptyState,
    PageHeaderCustom,
    ResultsHeader,
} from './ExperimentView/components'
import { DataCollection } from './ExperimentView/DataCollection'
import { DistributionTable } from './ExperimentView/DistributionTable'
import { ExperimentExposureModal, ExperimentGoalModal, Goal } from './ExperimentView/Goal'
import { Info } from './ExperimentView/Info'
import { Overview } from './ExperimentView/Overview'
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
                    <LoadingState />
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
                                        <DataCollection />
                                    </div>
                                </div>
                                <Results />
                            </>
                        ) : (
                            <>
                                <div className="xl:flex">
                                    <div className="w-1/2 pr-2">
                                        <Goal />
                                    </div>

                                    <div className="w-1/2 xl:pl-2 mt-8 xl:mt-0">
                                        <DataCollection />
                                    </div>
                                </div>
                                <ExperimentImplementationDetails experiment={experiment} />
                                {experiment.start_date && (
                                    <div>
                                        <ResultsHeader />
                                        <NoResultsEmptyState />
                                    </div>
                                )}
                            </>
                        )}
                        <ExperimentGoalModal experimentId={experimentId} />
                        <ExperimentExposureModal experimentId={experimentId} />
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
    const { experimentId, editingExistingExperiment, experimentMissing } = useValues(experimentLogic)

    if (experimentMissing) {
        return <NotFound object="experiment" />
    }

    return experimentId === 'new' || editingExistingExperiment ? <ExperimentForm /> : <ExperimentView />
}
