import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
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
import { experimentSceneLogic } from '../experimentSceneLogic'
import { ExperimentMetricModal } from '../Metrics/ExperimentMetricModal'
import { experimentMetricModalLogic } from '../Metrics/experimentMetricModalLogic'
import { MetricSourceModal } from '../Metrics/MetricSourceModal'
import { SharedMetricDetailsModal } from '../Metrics/SharedMetricDetailsModal'
import { SharedMetricModal } from '../Metrics/SharedMetricModal'
import { sharedMetricModalLogic } from '../Metrics/sharedMetricModalLogic'
import { Metrics } from '../MetricsView/new/Metrics'
import { RecalculationStatus } from '../MetricsView/shared/RecalculationStatus'
import { isLegacyExperiment } from '../utils'
import { DistributionModal, DistributionTable } from './DistributionTable'
import { ExperimentDebugPanel } from './ExperimentExecutionPathComparison'
import { ExperimentFeedbackTab } from './ExperimentFeedbackTab'
import { ExperimentHeader } from './ExperimentHeader'
import { EditConclusionModal } from './ExperimentModals'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'
import { ExposureCriteriaModal } from './ExposureCriteria'
import { Exposures } from './Exposures'
import { Info } from './Info'
import { LoadingState } from './LoadingState'
import { MultiVariantBiasWarning } from './MultiVariantBiasWarning'
import { PageHeaderCustom } from './PageHeader'
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
    const { experiment, orderedPrimaryMetricsWithResults, orderedSecondaryMetricsWithResults, isExperimentLaunched } =
        useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasMetrics = orderedPrimaryMetricsWithResults.length > 0 || orderedSecondaryMetricsWithResults.length > 0
    const showRecalculationStatus = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION] && hasMetrics

    return (
        <>
            <ResultsNotificationBanner />

            <div className="w-full mb-4">
                <Exposures />
                <MultiVariantBiasWarning />
            </div>

            {showRecalculationStatus && (
                <div className="mb-2">
                    <RecalculationStatus experiment={experiment} />
                </div>
            )}

            {/* Modern metrics view */}
            {!hasMetrics ? (
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

export function ExperimentView(): JSX.Element {
    const { experimentLoading, experimentId, experiment, isExperimentDraft, exposureCriteria, showDebugPanel } =
        useValues(experimentLogic)
    const {
        setExperiment,
        setExposureCriteria,
        updateExposureCriteria,
        updateExperimentMetrics,
        addSharedMetricsToExperiment,
        removeSharedMetricFromExperiment,
        removeMetric,
    } = useActions(experimentLogic)

    const { activeTabKey } = useValues(experimentSceneLogic)
    const { setActiveTabKey } = useActions(experimentSceneLogic)

    const { closeExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { closeSharedMetricModal } = useActions(sharedMetricModalLogic)

    // Branch to legacy view for legacy experiments
    if (!experimentLoading && isLegacyExperiment(experiment)) {
        return <LegacyExperimentView />
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
                    <Info />
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

                            removeMetric(metric.uuid, context.type)
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
                    <DistributionModal />
                    <ReleaseConditionsModal />

                    <EditConclusionModal />
                </>
            )}
        </SceneContent>
    )
}
