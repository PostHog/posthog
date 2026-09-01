import { useActions, useValues } from 'kea'

import { LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ActivityScope } from '~/types'

import { LegacyExperimentView } from 'products/experiments/frontend/legacy'

import { EmptyMetricsPanel } from '../ExperimentForm/MetricsPanel/EmptyMetricsPanel'
import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { DEFAULT_EXPERIMENT_TAB, type ExperimentTab, experimentSceneLogic } from '../experimentSceneLogic'
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
import { ExperimentReplayTab } from './ExperimentReplayTab'
import { ExperimentWarningBanner } from './ExperimentWarningBanners'
import { ExposureCriteriaModal } from './ExposureCriteria'
import { Exposures } from './Exposures'
import { Hypothesis } from './Hypothesis'
import { Info } from './Info'
import { LoadingState } from './LoadingState'
import { MultiVariantBiasWarning } from './MultiVariantBiasWarning'
import { PageHeaderCustom } from './PageHeader'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { ResultsNotificationBanner } from './ResultsNotificationBanner'
import { SettingsTab } from './SettingsTab'

const MetricsTab = (): JSX.Element => {
    const { experiment, orderedPrimaryMetricsWithResults, orderedSecondaryMetricsWithResults, isExperimentLaunched } =
        useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasMetrics = orderedPrimaryMetricsWithResults.length > 0 || orderedSecondaryMetricsWithResults.length > 0
    const showRecalculationStatus = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION] && hasMetrics

    return (
        <>
            <ResultsNotificationBanner />

            <div className="w-full mb-4 flex flex-col gap-4">
                <Hypothesis />
                <div>
                    <Exposures />
                    <MultiVariantBiasWarning />
                </div>
            </div>

            {showRecalculationStatus && <RecalculationStatus experiment={experiment} />}

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
    const { experimentLoading, experimentId, experiment, exposureCriteria, showDebugPanel } = useValues(experimentLogic)
    const {
        setExperiment,
        setExposureCriteria,
        updateExposureCriteria,
        updateExperimentMetrics,
        addSharedMetricsToExperiment,
        removeSharedMetricFromExperiment,
        removeMetric,
    } = useActions(experimentLogic)

    const { activeTabKey, availableTabs } = useValues(experimentSceneLogic)
    const { setActiveTabKey } = useActions(experimentSceneLogic)

    const { closeExperimentMetricModal } = useActions(experimentMetricModalLogic)
    const { closeSharedMetricModal } = useActions(sharedMetricModalLogic)

    // Branch to legacy view for legacy experiments
    if (!experimentLoading && isLegacyExperiment(experiment)) {
        return <LegacyExperimentView />
    }

    // Ordered as: results (Metrics), configuration (Settings, Code, Variants),
    // feature tabs (Recordings, User feedback), audit trail (History). Which of these actually
    // render is resolved by experimentSceneLogic's availableTabs, so the tab set, the URL, and the
    // tracked tab stay in agreement.
    const tabs: LemonTab<ExperimentTab>[] = (
        [
            { key: 'metrics', label: 'Metrics', content: <MetricsTab /> },
            { key: 'settings', label: 'Settings', content: <SettingsTab /> },
            { key: 'code', label: 'Code', content: <CodeTab /> },
            { key: 'variants', label: 'Variants', content: <VariantsTab /> },
            { key: 'recordings', label: 'Recordings', content: <ExperimentReplayTab experiment={experiment} /> },
            { key: 'feedback', label: 'User feedback', content: <ExperimentFeedbackTab experiment={experiment} /> },
            {
                key: 'history',
                label: 'History',
                content: <ActivityLog scope={ActivityScope.EXPERIMENT} id={experimentId} />,
            },
        ] satisfies LemonTab<ExperimentTab>[]
    ).filter((tab) => availableTabs.includes(tab.key))

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
                        // Fall back to the default tab if the active one is conditionally hidden
                        activeKey={tabs.some((tab) => tab.key === activeTabKey) ? activeTabKey : DEFAULT_EXPERIMENT_TAB}
                        onChange={(key) => setActiveTabKey(key)}
                        sceneInset
                        // Keep the tab bar full-width, but cap the content under each tab for readability
                        tabs={tabs.map((tab) =>
                            'content' in tab
                                ? {
                                      ...tab,
                                      content: <div className="w-full max-w-[1400px] mx-auto">{tab.content}</div>,
                                  }
                                : tab
                        )}
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
