import { LemonDivider, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { PostHogFeature } from 'posthog-js/react'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { MetricModal } from '../Metrics/MetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { MetricsView } from '../MetricsView/MetricsView'
import {
    ExperimentLoadingAnimation,
    ExploreButton,
    LoadingState,
    NoResultsEmptyState,
    PageHeaderCustom,
    ResultsHeader,
    ResultsQuery,
} from './components'
import { CumulativeExposuresChart } from './CumulativeExposuresChart'
import { DataCollection } from './DataCollection'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { Goal } from './Goal'
import { Info } from './Info'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { Results } from './Results'
import { SecondaryMetricsTable } from './SecondaryMetricsTable'
import { SummaryTable } from './SummaryTable'

const NewResultsTab = (): JSX.Element => {
    const { experiment, metricResults } = useValues(experimentLogic)
    const hasSomeResults = metricResults?.some((result) => result?.insight)

    const hasSinglePrimaryMetric = experiment.metrics.length === 1

    return (
        <>
            {!hasSomeResults && (
                <>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </>
            )}
            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && (
                <div className="mb-4">
                    <Overview />
                </div>
            )}
            <MetricsView isSecondary={false} />
            {/* Show detailed results if there's only a single primary metric */}
            {hasSomeResults && hasSinglePrimaryMetric && (
                <div>
                    <div className="pb-4">
                        <SummaryTable metric={experiment.metrics[0]} metricIndex={0} isSecondary={false} />
                    </div>
                    <div className="flex justify-end">
                        <ExploreButton result={metricResults?.[0] || null} size="xsmall" />
                    </div>
                    <div className="pb-4">
                        <ResultsQuery result={metricResults?.[0] || null} showTable={true} />
                    </div>
                </div>
            )}
            <MetricsView isSecondary={true} />
        </>
    )
}

const OldResultsTab = (): JSX.Element => {
    const { experiment, metricResults } = useValues(experimentLogic)
    const hasSomeResults = metricResults?.some((result) => result?.insight)

    return (
        <>
            {hasSomeResults ? (
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
            <SecondaryMetricsTable experimentId={experiment.id} />
        </>
    )
}

const ResultsTab = (): JSX.Element => {
    const { featureFlags } = useValues(experimentLogic)
    return <>{featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] ? <NewResultsTab /> : <OldResultsTab />}</>
}

const VariantsTab = (): JSX.Element => {
    return (
        <div className="space-y-8">
            <ReleaseConditionsTable />
            <DistributionTable />
            <PostHogFeature flag="experiments-cumulative-exposures-chart" match="test">
                <CumulativeExposuresChart />
            </PostHogFeature>
        </div>
    )
}

export function ExperimentView(): JSX.Element {
    const {
        experimentLoading,
        metricResultsLoading,
        secondaryMetricResultsLoading,
        experimentId,
        metricResults,
        tabKey,
        featureFlags,
    } = useValues(experimentLogic)

    const { setTabKey } = useActions(experimentLogic)
    // Instead, check if any result in the array has an insight
    const hasSomeResults = metricResults?.some((result) => result?.insight)

    return (
        <>
            <PageHeaderCustom />
            <div className="space-y-8 experiment-view">
                {experimentLoading ? (
                    <LoadingState />
                ) : (
                    <>
                        <Info />
                        {metricResultsLoading || secondaryMetricResultsLoading ? (
                            <ExperimentLoadingAnimation />
                        ) : (
                            <>
                                {hasSomeResults && !featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] ? (
                                    <div>
                                        <h2 className="font-semibold text-lg">Summary</h2>
                                        <Overview />
                                        <LemonDivider className="mt-4" />
                                    </div>
                                ) : null}
                                <div className="xl:flex">
                                    {featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] ? (
                                        <div className="w-1/2 mt-8 xl:mt-0">
                                            <DataCollection />
                                        </div>
                                    ) : (
                                        <>
                                            <div className="w-1/2 pr-2">
                                                <Goal />
                                            </div>
                                            <div className="w-1/2 xl:pl-2 mt-8 xl:mt-0">
                                                <DataCollection />
                                            </div>
                                        </>
                                    )}
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
                        <MetricSourceModal experimentId={experimentId} isSecondary={true} />
                        <MetricSourceModal experimentId={experimentId} isSecondary={false} />

                        <MetricModal experimentId={experimentId} isSecondary={true} />
                        <MetricModal experimentId={experimentId} isSecondary={false} />

                        <SharedMetricModal experimentId={experimentId} isSecondary={true} />
                        <SharedMetricModal experimentId={experimentId} isSecondary={false} />

                        <DistributionModal experimentId={experimentId} />
                        <ReleaseConditionsModal experimentId={experimentId} />
                    </>
                )}
            </div>
        </>
    )
}
