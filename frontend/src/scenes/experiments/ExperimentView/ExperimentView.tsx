import { LemonDivider, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { FEATURE_FLAGS } from 'lib/constants'
import { PostHogFeature } from 'posthog-js/react'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { MetricModal } from '../Metrics/MetricModal'
import { MetricsView } from '../MetricsView/MetricsView'
import {
    ExperimentLoadingAnimation,
    LoadingState,
    NoResultsEmptyState,
    PageHeaderCustom,
    ResultsHeader,
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

const ResultsTab = (): JSX.Element => {
    const { experiment, metricResults, featureFlags } = useValues(experimentLogic)
    const result = metricResults?.[0]
    const hasResultsInsight = result && result.insight

    return (
        <div className="space-y-8">
            {featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] ? (
                <MetricsView />
            ) : hasResultsInsight ? (
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
            {featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] ? (
                <MetricsView isSecondary={true} />
            ) : (
                <SecondaryMetricsTable experimentId={experiment.id} />
            )}
        </div>
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
    const result = metricResults?.[0]
    const hasResultsInsight = result && result.insight

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
                                {hasResultsInsight && !featureFlags[FEATURE_FLAGS.EXPERIMENTS_MULTIPLE_METRICS] ? (
                                    <div>
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
                        <MetricModal experimentId={experimentId} isSecondary={true} />
                        <MetricModal experimentId={experimentId} isSecondary={false} />

                        <DistributionModal experimentId={experimentId} />
                        <ReleaseConditionsModal experimentId={experimentId} />
                    </>
                )}
            </div>
        </>
    )
}
