import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'
import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from 'scenes/experiments/constants'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import type { CachedExperimentQueryResponse } from '~/queries/schema/schema-general'
import {
    LegacyExperimentInfo,
    LegacyResultsQuery,
    LegacyExploreButton,
    LegacyExperimentHeader,
    LegacyMetricsView,
} from '~/scenes/experiments/legacy'
import { ActivityScope } from '~/types'

import {
    ExploreAsInsightButton,
    ResultsBreakdown,
    ResultsBreakdownSkeleton,
    ResultsInsightInfoBanner,
    ResultsQuery,
} from '../components/ResultsBreakdown'
import { SummarizeExperimentButton } from '../components/SummarizeExperimentButton'
import { SummarizeSessionReplaysButton } from '../components/SummarizeSessionReplaysButton'
import { EmptyMetricsPanel } from '../ExperimentForm/MetricsPanel/EmptyMetricsPanel'
import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import type { ExperimentSceneLogicProps } from '../experimentSceneLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { LegacyEditConclusionModal } from '../legacy/LegacyEditConclusionModal'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { experimentMetricModalLogic } from '../Metrics/experimentMetricModalLogic'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricDetailsModal } from '../Metrics/SharedMetricDetailsModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { sharedMetricModalLogic } from '../Metrics/sharedMetricModalLogic'
import { Metrics } from '../MetricsView/new/Metrics'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import { isLegacyExperiment, isLegacyExperimentQuery } from '../utils'
import { EditConclusionModal, LoadingState, PageHeaderCustom } from './components'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentDebugPanel } from './ExperimentExecutionPathComparison'
import { ExperimentFeedbackTab } from './ExperimentFeedbackTab'
import { ExperimentHeader } from './ExperimentHeader'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'
import { ExposureCriteriaModal } from './ExposureCriteria'
import { Exposures } from './Exposures'
import { Info } from './Info'
import { Overview } from './Overview'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { ResultsNotificationBanner } from './ResultsNotificationBanner'
import { SettingsTab } from './SettingsTab'
import { SummaryTable } from './SummaryTable'

const AiAnalysisTab = (): JSX.Element => {
    const { experiment, hasMinimumExposureForResults } = useValues(experimentLogic)

    return (
        <div className="flex flex-col gap-4 items-start">
            <div className="flex flex-col gap-1 items-start">
                <SummarizeExperimentButton
                    disabledReason={
                        !hasMinimumExposureForResults
                            ? `Experiment needs at least ${EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS} exposures to summarize results.`
                            : undefined
                    }
                />
                <p className="text-muted text-xs m-0">
                    Analyze your experiment's metric results, statistical significance, and variant performance using
                    AI.
                </p>
            </div>
            <div className="flex flex-col gap-1 items-start">
                <SummarizeSessionReplaysButton experiment={experiment} />
                <p className="text-muted text-xs m-0">
                    Compare session recordings across variants to identify differences in user behavior.
                </p>
            </div>
        </div>
    )
}

const MetricsTab = (): JSX.Element => {
    const {
        experiment,
        legacyPrimaryMetricsResults,
        firstPrimaryMetric,
        primaryMetricsLengthWithSharedMetrics,
        hasMinimumExposureForResults,
        usesNewQueryRunner,
        orderedPrimaryMetricsWithResults,
        orderedSecondaryMetricsWithResults,
        isExperimentLaunched,
    } = useValues(experimentLogic)
    /**
     * we still use the legacy metric results here. Results on the new format are loaded
     * in the primaryMetricsResults state key. We'll eventually move into using the new state.
     */
    const hasSomeResults = legacyPrimaryMetricsResults?.some((result) => result?.insight)

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

    const firstPrimaryMetricResult = legacyPrimaryMetricsResults?.[0]

    const hasLegacyResults = legacyPrimaryMetricsResults.some((result) => result != null)

    /**
     * Show a detailed results if:
     * - there's a single primary metric
     * - if the metric has insight results
     * - if we have the minimum number of exposures
     * - if it's the first primary metric (?)
     *
     * this is only for legacy experiments.
     */
    const showResultDetails =
        hasSomeResults &&
        hasMinimumExposureForResults &&
        hasSinglePrimaryMetric &&
        firstPrimaryMetric &&
        firstPrimaryMetricResult

    return (
        <>
            <ResultsNotificationBanner />

            {usesNewQueryRunner && (
                <div className="w-full mb-4">
                    <Exposures />
                </div>
            )}

            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && hasMinimumExposureForResults && (
                <div className="mb-4 mt-2">
                    <Overview metricUuid={firstPrimaryMetric?.uuid || ''} />
                </div>
            )}
            {/**
             *  check if we should render the legacy metrics view or the new one
             */}
            {isLegacyExperiment(experiment) || hasLegacyResults ? (
                <>
                    <LegacyMetricsView isSecondary={false} />
                    {showResultDetails && (
                        <div>
                            <div className="pb-4">
                                <SummaryTable metric={firstPrimaryMetric} displayOrder={0} isSecondary={false} />
                            </div>
                            {isLegacyExperimentQuery(firstPrimaryMetricResult) ? (
                                <>
                                    <div className="flex justify-end">
                                        <LegacyExploreButton result={firstPrimaryMetricResult} size="xsmall" />
                                    </div>
                                    <div className="pb-4">
                                        <LegacyResultsQuery
                                            result={firstPrimaryMetricResult || null}
                                            showTable={true}
                                        />
                                    </div>
                                </>
                            ) : (
                                /**
                                 * altough we don't have a great typeguard here, we know that the result is a CachedExperimentQueryResponse
                                 * because we're only showing results for experiment queries (legacy check)
                                 */
                                <ResultsBreakdown
                                    result={firstPrimaryMetricResult as CachedExperimentQueryResponse}
                                    experiment={experiment}
                                    metricUuid={firstPrimaryMetric?.uuid || ''}
                                    isPrimary={true}
                                >
                                    {({
                                        query,
                                        breakdownResults,
                                        breakdownResultsLoading,
                                        exposureDifference,
                                        breakdownLastRefresh,
                                    }) => (
                                        <div>
                                            {breakdownResultsLoading && <ResultsBreakdownSkeleton />}
                                            {query && breakdownResults && (
                                                <div>
                                                    <div className="flex justify-end">
                                                        <ExploreAsInsightButton query={query} />
                                                    </div>
                                                    <ResultsInsightInfoBanner exposureDifference={exposureDifference} />
                                                    <div className="pb-4">
                                                        <ResultsQuery
                                                            query={query}
                                                            breakdownResults={breakdownResults}
                                                            breakdownLastRefresh={breakdownLastRefresh}
                                                        />
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </ResultsBreakdown>
                            )}
                        </div>
                    )}
                    <LegacyMetricsView isSecondary={true} />
                </>
            ) : orderedPrimaryMetricsWithResults.length === 0 && orderedSecondaryMetricsWithResults.length === 0 ? (
                <EmptyMetricsPanel isLaunched={isExperimentLaunched} />
            ) : (
                <>
                    <Metrics isSecondary={false} />
                    <Metrics isSecondary={true} />
                </>
            )}
        </>
    )
}

const CodeTab = (): JSX.Element => {
    const { experiment } = useValues(experimentLogic)

    return (
        <>
            {experiment.type === 'web' ? (
                <WebExperimentImplementationDetails experiment={experiment} />
            ) : (
                <ExperimentImplementationDetails experiment={experiment} />
            )}
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

export function ExperimentView({ tabId }: Pick<ExperimentSceneLogicProps, 'tabId'>): JSX.Element {
    const {
        experimentLoading,
        experimentId,
        experiment,
        usesNewQueryRunner,
        isExperimentDraft,
        exposureCriteria,
        showDebugPanel,
    } = useValues(experimentLogic)
    const {
        setExperiment,
        setExposureCriteria,
        updateExposureCriteria,
        updateExperimentMetrics,
        addSharedMetricsToExperiment,
        removeSharedMetricFromExperiment,
    } = useActions(experimentLogic)

    if (!tabId) {
        throw new Error('<ExperimentView /> must receive a tabId prop')
    }

    const { activeTabKey } = useValues(experimentSceneLogic({ tabId }))
    const { setActiveTabKey } = useActions(experimentSceneLogic({ tabId }))

    const { closeExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { closeSharedMetricModal } = useActions(sharedMetricModalLogic)

    return (
        <SceneContent>
            <PageHeaderCustom />
            {experimentLoading ? (
                <LoadingState />
            ) : (
                <>
                    <ExperimentWarningBanner />
                    {showDebugPanel && (
                        <div className="mb-4">
                            <ExperimentDebugPanel
                                experimentId={typeof experiment.id === 'number' ? experiment.id : null}
                            />
                        </div>
                    )}
                    {!usesNewQueryRunner && (
                        <LemonBanner type="warning" className="mb-4">
                            This is a legacy experiment. Metrics can no longer be edited.
                        </LemonBanner>
                    )}
                    {experiment.feature_flag?.id && (
                        <PendingChangeRequestBanner
                            resourceType="feature_flag"
                            resourceId={experiment.feature_flag.id}
                            context="experiment"
                        />
                    )}
                    {usesNewQueryRunner ? <Info tabId={tabId} /> : <LegacyExperimentInfo />}
                    {usesNewQueryRunner ? <ExperimentHeader /> : <LegacyExperimentHeader />}
                    <LemonTabs
                        activeKey={activeTabKey}
                        onChange={(key) => setActiveTabKey(key)}
                        sceneInset
                        tabs={[
                            ...(usesNewQueryRunner
                                ? [
                                      {
                                          key: 'settings',
                                          label: 'Settings',
                                          content: <SettingsTab />,
                                      },
                                  ]
                                : []),
                            {
                                key: 'metrics',
                                label: 'Metrics',
                                content: <MetricsTab />,
                            },
                            ...(usesNewQueryRunner
                                ? [
                                      {
                                          key: 'ai_analysis',
                                          label: (
                                              <div className="flex items-center gap-1">
                                                  <IconSparkles />
                                                  <span>AI analysis</span>
                                              </div>
                                          ),
                                          content: <AiAnalysisTab />,
                                      },
                                  ]
                                : []),
                            ...(!isExperimentDraft
                                ? [
                                      {
                                          key: 'code',
                                          label: 'Code',
                                          content: <CodeTab />,
                                      },
                                  ]
                                : []),
                            {
                                key: 'variants',
                                label: 'Variants',
                                content: <VariantsTab />,
                            },
                            {
                                key: 'history',
                                label: 'History',
                                content: <ActivityLog scope={ActivityScope.EXPERIMENT} id={experimentId} />,
                            },
                            ...(experiment.feature_flag
                                ? [
                                      {
                                          key: 'feedback',
                                          label: 'User feedback',
                                          content: <ExperimentFeedbackTab experiment={experiment} />,
                                      },
                                  ]
                                : []),
                        ]}
                    />

                    {usesNewQueryRunner ? (
                        <>
                            <MetricSourceModal />
                            <ExperimentMetricModal
                                experiment={experiment}
                                exposureCriteria={exposureCriteria}
                                onSave={(metric, context) => {
                                    const metrics = experiment[context.field]
                                    const isNew = !metrics.some(({ uuid }) => uuid === metric.uuid)

                                    setExperiment({
                                        [context.field]: isNew
                                            ? [...metrics, metric]
                                            : metrics.map((m) => (m.uuid === metric.uuid ? metric : m)),
                                    })

                                    updateExperimentMetrics()
                                    closeExperimentMetricModal()
                                }}
                                onDelete={(metric, context) => {
                                    if (!metric.uuid) {
                                        return
                                    }

                                    setExperiment({
                                        [context.field]: experiment[context.field].filter(
                                            (m) => m.uuid !== metric.uuid
                                        ),
                                    })

                                    updateExperimentMetrics()
                                    closeExperimentMetricModal()
                                }}
                            />
                            <SharedMetricModal
                                experiment={experiment}
                                onSave={(metrics, context) => {
                                    addSharedMetricsToExperiment(
                                        metrics.map(({ id }) => id),
                                        { type: context.type }
                                    )
                                    closeSharedMetricModal()
                                }}
                            />
                            <SharedMetricDetailsModal onDelete={removeSharedMetricFromExperiment} />
                            <ExposureCriteriaModal
                                onSave={(exposureCriteria) => {
                                    setExposureCriteria(exposureCriteria)
                                    /**
                                     * this will trigger a save of the experiment and
                                     * a refresh of the results
                                     */
                                    updateExposureCriteria()
                                }}
                            />
                            <RunningTimeCalculatorModal />
                        </>
                    ) : null}

                    <DistributionModal />
                    <ReleaseConditionsModal />

                    <EditConclusionModal />
                    <LegacyEditConclusionModal />
                </>
            )}
        </SceneContent>
    )
}
