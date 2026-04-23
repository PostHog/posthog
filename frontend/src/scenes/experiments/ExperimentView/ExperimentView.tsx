import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'
import { EXPERIMENT_MIN_EXPOSURES_FOR_RESULTS } from 'scenes/experiments/constants'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { LegacyExperimentView } from '~/scenes/experiments/legacy'
import { ActivityScope } from '~/types'

import { SummarizeExperimentButton } from '../components/SummarizeExperimentButton'
import { SummarizeSessionReplaysButton } from '../components/SummarizeSessionReplaysButton'
import { EmptyMetricsPanel } from '../ExperimentForm/MetricsPanel/EmptyMetricsPanel'
import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import type { ExperimentSceneLogicProps } from '../experimentSceneLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { experimentMetricModalLogic } from '../Metrics/experimentMetricModalLogic'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricDetailsModal } from '../Metrics/SharedMetricDetailsModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { sharedMetricModalLogic } from '../Metrics/sharedMetricModalLogic'
import { Metrics } from '../MetricsView/new/Metrics'
import { RunningTimeCalculatorModal } from '../RunningTimeCalculator/RunningTimeCalculatorModal'
import { isLegacyExperiment } from '../utils'
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
        firstPrimaryMetric,
        primaryMetricsLengthWithSharedMetrics,
        hasMinimumExposureForResults,
        orderedPrimaryMetricsWithResults,
        orderedSecondaryMetricsWithResults,
        isExperimentLaunched,
    } = useValues(experimentLogic)

    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1

    return (
        <>
            <ResultsNotificationBanner />

            <div className="w-full mb-4">
                <Exposures />
            </div>

            {/* Show overview if there's only a single primary metric */}
            {hasSinglePrimaryMetric && hasMinimumExposureForResults && (
                <div className="mb-4 mt-2">
                    <Overview metricUuid={firstPrimaryMetric?.uuid || ''} />
                </div>
            )}

            {/* Modern metrics view */}
            {orderedPrimaryMetricsWithResults.length === 0 && orderedSecondaryMetricsWithResults.length === 0 ? (
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
    const { experimentLoading, experimentId, experiment, isExperimentDraft, exposureCriteria, showDebugPanel } =
        useValues(experimentLogic)
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

    // Branch to legacy view for legacy experiments
    if (!experimentLoading && isLegacyExperiment(experiment)) {
        return <LegacyExperimentView tabId={tabId} />
    }

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
                    {experiment.feature_flag?.id && (
                        <PendingChangeRequestBanner
                            resourceType="feature_flag"
                            resourceId={experiment.feature_flag.id}
                            context="experiment"
                        />
                    )}
                    <Info tabId={tabId} />
                    <ExperimentHeader />
                    <LemonTabs
                        activeKey={activeTabKey}
                        onChange={(key) => setActiveTabKey(key)}
                        sceneInset
                        tabs={[
                            {
                                key: 'settings',
                                label: 'Settings',
                                content: <SettingsTab />,
                            },
                            {
                                key: 'metrics',
                                label: 'Metrics',
                                content: <MetricsTab />,
                            },
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

                    {/* Modern experiment modals */}
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
                                [context.field]: experiment[context.field].filter((m) => m.uuid !== metric.uuid),
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

                    <DistributionModal />
                    <ReleaseConditionsModal />

                    <EditConclusionModal />
                </>
            )}
        </SceneContent>
    )
}
