import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { LegacyMetricModal } from '../Metrics/LegacyMetricModal'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { MetricsView } from '../MetricsView/MetricsView'
import { VariantDeltaTimeseries } from '../MetricsView/VariantDeltaTimeseries'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import {
    EditConclusionModal,
    ExploreButton,
    LoadingState,
    PageHeaderCustom,
    ResultsQuery,
    StopExperimentModal,
} from './components'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentHeader } from './ExperimentHeader'
import { ExposureCriteriaModal } from './ExposureCriteria'
import { Info } from './Info'
import { LegacyExperimentHeader } from './LegacyExperimentHeader'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { SummaryTable } from './SummaryTable'
import { PersonSummariesTable } from 'scenes/trends/persons-modal/PersonsModal'

const ResultsTab = (): JSX.Element => {
    const {
        experiment,
        metricResults,
        firstPrimaryMetric,
        primaryMetricsLengthWithSharedMetrics,
        metricResultsLoading,
        hasMinimumExposureForResults,
    } = useValues(experimentLogic)
    const hasSomeResults = metricResults?.some((result) => result?.insight)

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

    return (
        <>
            {!experiment.start_date && !metricResultsLoading && (
                <>
                    {experiment.type === 'web' ? (
                        <WebExperimentImplementationDetails experiment={experiment} />
                    ) : (
                        <ExperimentImplementationDetails experiment={experiment} />
                    )}
                </>
            )}
            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && hasMinimumExposureForResults && (
                <div className="mb-4 mt-2">
                    <Overview />
                </div>
            )}
            <MetricsView isSecondary={false} />
            {/* Show detailed results if there's only a single primary metric */}
            {hasSomeResults && hasMinimumExposureForResults && hasSinglePrimaryMetric && firstPrimaryMetric && (
                <div>
                    <div className="pb-4">
                        <SummaryTable metric={firstPrimaryMetric} metricIndex={0} isSecondary={false} />
                    </div>
                    {/* TODO: Only show explore button results viz if the metric is a trends or funnels query. Not supported yet with new query runner */}
                    {metricResults?.[0] &&
                        (metricResults[0].kind === 'ExperimentTrendsQuery' ||
                            metricResults[0].kind === 'ExperimentFunnelsQuery') && (
                            <>
                                <div className="flex justify-end">
                                    <ExploreButton result={metricResults[0]} size="xsmall" />
                                </div>
                                <div className="pb-4">
                                    <ResultsQuery result={metricResults?.[0] || null} showTable={true} />
                                </div>
                            </>
                        )}
                </div>
            )}
            <MetricsView isSecondary={true} />
        </>
    )
}

const VariantsTab = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-8 mt-2">
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

const experimentSummaryData = {
    id: 1,
    period: '2024-03-01 to 2024-03-15',
    sessionsAnalyzed: 250,
    keyInsights: 4,
    pains: 1,
    status: 'success',
    details: {
        criticalIssues: [
            {
                description: 'Personalization preferences unclear',
                sessions: [
                    {
                        id: '0196d2be-108d-7a79-8048-e5234ad7bdc9',
                        timestamp: '2024-03-15 14:23:45',
                        hasRecording: true,
                        summary: 'Users spend time exploring personalization options but struggle to make selections',
                    },
                    {
                        id: '0196d2be-108d-7a79-8048-e5234ad7bdc8',
                        timestamp: '2024-03-12 11:15:22',
                        hasRecording: true,
                        summary: 'Some users skip personalization step entirely to reach signup faster',
                    },
                ],
            },
        ],
        commonJourneys: [
            {
                name: 'Quick Signup Pattern',
                path: 'Homepage → New Signup → Skip Personalization → Complete Signup',
            },
            {
                name: 'Exploratory Pattern',
                path: 'Homepage → New Signup → Explore Options → Complete Signup',
            },
            {
                name: 'Comparison Pattern',
                path: 'Homepage → New Signup → Compare Options → Complete Signup',
            },
        ],
        edgeCases: [
            {
                description: 'Users requesting more personalization options',
                sessions: [
                    {
                        id: '0196d2bd-515c-7230-9e15-a2a437f2e3e5',
                        timestamp: '2024-03-11 09:45:12',
                        hasRecording: true,
                        summary: 'Users actively looking for more customization options in the new flow',
                    },
                ],
            },
        ],
        summary: 'New personalized signup flow shows promising results with 25% higher completion rate. Users appreciate the customization options but some prefer faster paths. Consider adding a "quick signup" option while maintaining personalization benefits.',
    },
}

export function ExperimentView(): JSX.Element {
    const { experimentLoading, experimentId, tabKey, shouldUseExperimentMetrics } = useValues(experimentLogic)

    const { setTabKey } = useActions(experimentLogic)

    return (
        <>
            <PageHeaderCustom />
            <div className="deprecated-space-y-8 experiment-view">
                {experimentLoading ? (
                    <LoadingState />
                ) : (
                    <>
                        <Info />
                        {shouldUseExperimentMetrics ? <ExperimentHeader /> : <LegacyExperimentHeader />}
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
                                {
                                    key: 'summary',
                                    label: 'Summary',
                                    content: <PersonSummariesTable data={experimentSummaryData} />,
                                },
                            ]}
                        />

                        <MetricSourceModal experimentId={experimentId} isSecondary={true} />
                        <MetricSourceModal experimentId={experimentId} isSecondary={false} />

                        {shouldUseExperimentMetrics ? (
                            <>
                                <ExperimentMetricModal experimentId={experimentId} isSecondary={true} />
                                <ExperimentMetricModal experimentId={experimentId} isSecondary={false} />
                                <ExposureCriteriaModal />
                                <RunningTimeCalculatorModal />
                            </>
                        ) : (
                            <>
                                <LegacyMetricModal experimentId={experimentId} isSecondary={true} />
                                <LegacyMetricModal experimentId={experimentId} isSecondary={false} />
                            </>
                        )}

                        <SharedMetricModal experimentId={experimentId} isSecondary={true} />
                        <SharedMetricModal experimentId={experimentId} isSecondary={false} />

                        <DistributionModal experimentId={experimentId} />
                        <ReleaseConditionsModal experimentId={experimentId} />

                        <StopExperimentModal experimentId={experimentId} />
                        <EditConclusionModal experimentId={experimentId} />

                        <VariantDeltaTimeseries />
                    </>
                )}
            </div>
        </>
    )
}
