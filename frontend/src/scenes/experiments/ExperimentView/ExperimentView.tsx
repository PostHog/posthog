import '../Experiment.scss'

import { LemonDivider, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import {
    ExperimentLoadingAnimation,
    LoadingState,
    NoResultsEmptyState,
    PageHeaderCustom,
    ResultsHeader,
} from './components'
import { DataCollection } from './DataCollection'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentExposureModal, ExperimentGoalModal, Goal } from './Goal'
import { Info } from './Info'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { Results } from './Results'
import { SecondaryMetricsTable } from './SecondaryMetricsTable'

const ResultsTab = (): JSX.Element => {
    const { experiment, experimentResults } = useValues(experimentLogic)
    const { updateExperimentSecondaryMetrics } = useActions(experimentLogic)

    const hasResultsInsight = experimentResults && experimentResults.insight

    return (
        <div className="space-y-8">
            {hasResultsInsight ? (
                <Results />
            ) : (
                <>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}

                    {experiment.start_date && (
                        <div>
                            <ResultsHeader />
                            <NoResultsEmptyState />
                        </div>
                    )}
                </>
            )}
            <SecondaryMetricsTable
                experimentId={experiment.id}
                onMetricsChange={(metrics) => updateExperimentSecondaryMetrics(metrics)}
                initialMetrics={experiment.secondary_metrics}
                defaultAggregationType={experiment.parameters?.aggregation_group_type_index}
            />
        </div>
    )
}

const VariantsTab = (): JSX.Element => {
    return (
        <div className="space-y-8">
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

export function ExperimentView(): JSX.Element {
    const { experimentLoading, experimentResultsLoading, experimentId, experimentResults, tabKey } =
        useValues(experimentLogic)

    const { setTabKey } = useActions(experimentLogic)

    const hasResultsInsight = experimentResults && experimentResults.insight

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
                        ) : (
                            <>
                                {hasResultsInsight ? (
                                    <div>
                                        <Overview />
                                        <LemonDivider className="mt-4" />
                                    </div>
                                ) : null}
                                <div className="xl:flex">
                                    <div className="w-1/2 pr-2">
                                        <Goal />
                                    </div>

                                    <div className="w-1/2 xl:pl-2 mt-8 xl:mt-0">
                                        <DataCollection />
                                    </div>
                                </div>
                                <LemonTabs
                                    activeKey={tabKey}
                                    onChange={(key) => setTabKey(key)}
                                    tabs={[
                                        {
                                            key: 'results',
                                            label: 'Results',
                                            content: <ResultsTab />,
                                        },
                                        {
                                            key: 'variants',
                                            label: 'Variants',
                                            content: <VariantsTab />,
                                        },
                                    ]}
                                />
                            </>
                        )}
                        <ExperimentGoalModal experimentId={experimentId} />
                        <ExperimentExposureModal experimentId={experimentId} />
                        <DistributionModal experimentId={experimentId} />
                        <ReleaseConditionsModal experimentId={experimentId} />
                    </>
                )}
            </div>
        </>
    )
}
