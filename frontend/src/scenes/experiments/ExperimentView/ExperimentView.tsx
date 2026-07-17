import { useActions, useAsyncActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FEATURE_FLAGS } from 'lib/constants'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'
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
    const { setExperiment, setExposureCriteria, updateExposureCriteria } = useActions(experimentLogic)
    const { updateExperimentMetrics, addSharedMetricsToExperiment, removeSharedMetricFromExperiment, removeMetric } =
        useAsyncActions(experimentLogic)

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
                        onSave={async (metric, context) => {
                            const metrics = experiment[context.field]
                            const isNew = !metrics.some(({ uuid }) => uuid === metric.uuid)

                            setExperiment({
                                [context.field]: isNew
                                    ? [...metrics, metric]
                                    : metrics.map((m) => (m.uuid === metric.uuid ? metric : m)),
                            })

                            try {
                                await updateExperimentMetrics()
                                lemonToast.success(
                                    `${capitalizeFirstLetter(context.type)} metric ${isNew ? 'added' : 'updated'}`
                                )
                                closeExperimentMetricModal()
                            } catch {
                                // Restore the metrics so the table doesn't show an unsaved change.
                                setExperiment({ [context.field]: metrics })
                                lemonToast.error(
                                    `Failed to ${isNew ? 'add' : 'update'} ${context.type} metric. Please try again.`
                                )
                                throw new Error('Failed to save metric')
                            }
                        }}
                        onDelete={async (metric, context) => {
                            if (!metric.uuid) {
                                return
                            }

                            try {
                                await removeMetric(metric.uuid, context.type)
                                lemonToast.success(`${capitalizeFirstLetter(context.type)} metric removed`)
                                closeExperimentMetricModal()
                            } catch {
                                lemonToast.error(`Failed to remove ${context.type} metric. Please try again.`)
                                throw new Error('Failed to remove metric')
                            }
                        }}
                    />
                    <SharedMetricModal
                        experiment={experiment}
                        onSave={async (metrics, context) => {
                            const metricLabel = pluralize(metrics.length, 'metric', 'metrics', false)
                            try {
                                await addSharedMetricsToExperiment(
                                    metrics.map(({ id }) => id),
                                    { type: context.type }
                                )
                                lemonToast.success(`${capitalizeFirstLetter(context.type)} shared ${metricLabel} added`)
                                closeSharedMetricModal()
                            } catch {
                                lemonToast.error(`Failed to add shared ${metricLabel}. Please try again.`)
                                throw new Error('Failed to add shared metrics')
                            }
                        }}
                    />
                    <SharedMetricDetailsModal
                        onDelete={async (sharedMetricId, context) => {
                            try {
                                await removeSharedMetricFromExperiment(sharedMetricId)
                                lemonToast.success(`${capitalizeFirstLetter(context.type)} shared metric removed`)
                            } catch {
                                lemonToast.error(`Failed to remove ${context.type} shared metric. Please try again.`)
                                throw new Error('Failed to remove shared metric')
                            }
                        }}
                    />
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
