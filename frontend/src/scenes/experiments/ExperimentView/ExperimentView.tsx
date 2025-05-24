import { LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'
import { PersonSummariesTable } from 'scenes/trends/persons-modal/PersonsModal'

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
    sessionsAnalyzed: 2338,
    keyInsights: 4,
    pains: 3,
    status: 'failure',
    details: {
        criticalIssues: [
            {
                description: 'Personalization step may cause confusion or friction',
                sessions: [
                    {
                        id: 'session-001',
                        timestamp: '2024-03-10 10:00:00',
                        hasRecording: true,
                        summary:
                            'Some users spent extra time on the personalization step and abandoned before completing signup.',
                    },
                    {
                        id: 'session-101',
                        timestamp: '2024-03-11 09:12:00',
                        hasRecording: true,
                        summary:
                            'Users hesitated at unclear questions in personalization, leading to drop-off or random answers.',
                    },
                ],
            },
            {
                description: 'Users in both variants struggled with password requirements',
                sessions: [
                    {
                        id: 'session-201',
                        timestamp: '2024-03-13 15:45:00',
                        hasRecording: true,
                        summary: 'Several users failed to meet password criteria and had to retry multiple times.',
                    },
                ],
            },
            {
                description: 'Mobile users experienced layout issues in the personalization step',
                sessions: [
                    {
                        id: 'session-301',
                        timestamp: '2024-03-14 17:20:00',
                        hasRecording: true,
                        summary: 'On mobile, some fields were cut off or hard to interact with, causing frustration.',
                    },
                ],
            },
        ],
        commonJourneys: [
            {
                name: 'Standard Signup (Control)',
                path: 'Homepage → Signup → Complete Signup',
            },
            {
                name: 'Personalized Signup (Test)',
                path: 'Homepage → Signup → Personalization → Complete Signup',
            },
            {
                name: 'Personalization Drop-off',
                path: 'Homepage → Signup → Personalization → Exit',
            },
            {
                name: 'Password Retry Loop',
                path: 'Homepage → Signup → (Password Error) → Retry → Complete Signup',
            },
        ],
        edgeCases: [
            {
                description: 'Users skipping or rushing through personalization',
                sessions: [
                    {
                        id: 'session-002',
                        timestamp: '2024-03-12 14:30:00',
                        hasRecording: true,
                        summary:
                            'Some users quickly skipped or provided minimal input on personalization to finish signup.',
                    },
                ],
            },
            {
                description: 'Users using autofill for all fields',
                sessions: [
                    {
                        id: 'session-401',
                        timestamp: '2024-03-15 11:05:00',
                        hasRecording: true,
                        summary:
                            'A subset of users used browser autofill, bypassing most friction but sometimes missing required personalization fields.',
                    },
                ],
            },
        ],
        summary:
            'The experiment confirmed that the personalized signup flow did not outperform control. Users struggled with unclear personalization questions, password requirements, and mobile layout issues. Many rushed or skipped personalization, reducing its value. Recommend simplifying the flow and making personalization optional.',
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
