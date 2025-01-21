import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { PostHogFeature } from 'posthog-js/react'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { MetricModal } from '../Metrics/MetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { MetricsView } from '../MetricsView/MetricsView'
import { ExperimentLoadingAnimation, ExploreButton, LoadingState, PageHeaderCustom, ResultsQuery } from './components'
import { CumulativeExposuresChart } from './CumulativeExposuresChart'
import { DataCollection } from './DataCollection'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { Info } from './Info'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { SummaryTable } from './SummaryTable'

const ResultsTab = (): JSX.Element => {
    const { experiment, metricResults, primaryMetricsLengthWithSharedMetrics } = useValues(experimentLogic)
    const hasSomeResults = metricResults?.some((result) => result?.insight)

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

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
    const { experimentLoading, metricResultsLoading, secondaryMetricResultsLoading, experimentId, tabKey } =
        useValues(experimentLogic)

    const { setTabKey } = useActions(experimentLogic)

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
                                <div className="xl:flex">
                                    <div className="w-1/2 mt-8 xl:mt-0">
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
