import { useActions, useValues } from 'kea'

import { LemonBanner, LemonTab, LemonTabs } from '@posthog/lemon-ui'

import { ActivityLog } from 'lib/components/ActivityLog/ActivityLog'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'
import { WebExperimentImplementationDetails } from 'scenes/experiments/WebExperimentImplementationDetails'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import { ActivityScope } from '~/types'

import { ExperimentMetaBar } from 'products/experiments/frontend/components/ExperimentMetaBar'
import { ExperimentHealthDebug } from 'products/experiments/frontend/health/ExperimentHealthDebug'
import { ExperimentHealthPanel } from 'products/experiments/frontend/health/ExperimentHealthPanel'
import { useHealthFindingReporting } from 'products/experiments/frontend/health/useHealthFindingReporting'
import { LegacyExperimentView } from 'products/experiments/frontend/legacy'
import { ExperimentMetricModal } from 'products/experiments/frontend/modals/ExperimentMetricModal/ExperimentMetricModal'
import { experimentMetricModalLogic } from 'products/experiments/frontend/modals/ExperimentMetricModal/experimentMetricModalLogic'
import { MetricSourceModal } from 'products/experiments/frontend/modals/MetricSourceModal/MetricSourceModal'
import { SharedMetricDetailsModal } from 'products/experiments/frontend/modals/SharedMetricDetailsModal/SharedMetricDetailsModal'
import { SharedMetricModal } from 'products/experiments/frontend/modals/SharedMetricModal/SharedMetricModal'
import { sharedMetricModalLogic } from 'products/experiments/frontend/modals/SharedMetricModal/sharedMetricModalLogic'

import { EmptyMetricsPanel } from '../ExperimentForm/MetricsPanel/EmptyMetricsPanel'
import { ExperimentImplementationDetails } from '../ExperimentImplementationDetails'
import { experimentLogic } from '../experimentLogic'
import { DEFAULT_EXPERIMENT_TAB, type ExperimentTab, experimentSceneLogic } from '../experimentSceneLogic'
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
import { LoadingState } from './LoadingState'
import { MultiVariantBiasWarning } from './MultiVariantBiasWarning'
import { PageHeaderCustom } from './PageHeader'
import { ReleaseConditionsModal, ReleaseConditionsTable } from './ReleaseConditionsTable'
import { ResultsNotificationBanner } from './ResultsNotificationBanner'
import { SettingsTab } from './SettingsTab'

const MetricsTab = (): JSX.Element => {
    const {
        experiment,
        orderedPrimaryMetricsWithResults,
        orderedSecondaryMetricsWithResults,
        isExperimentLaunched,
        healthFindings,
        browserNoMetricsWarning,
    } = useValues(experimentLogic)
    const { featureFlags } = useValues(featureFlagLogic)

    const hasMetrics = orderedPrimaryMetricsWithResults.length > 0 || orderedSecondaryMetricsWithResults.length > 0
    const showRecalculationStatus = !!featureFlags[FEATURE_FLAGS.EXPERIMENTS_METRICS_RECALCULATION] && hasMetrics

    // With health findings, the health panel above the tabs shows the "No metrics defined" and bias warnings.
    const showsHealthPanel = healthFindings !== null
    const showNoMetricsWarning = !showsHealthPanel && browserNoMetricsWarning
    const hasNoMetricFinding = showsHealthPanel
        ? healthFindings.some(({ code }) => code === 'no_metric')
        : showNoMetricsWarning
    // The add metric buttons below act on the finding also when the health panel shows it.
    const { reportActedOn: reportNoMetricActedOn } = useHealthFindingReporting(
        hasNoMetricFinding ? { code: 'no_metric' } : null,
        !showsHealthPanel
    )

    return (
        <>
            <ResultsNotificationBanner />

            <div className="w-full mb-4 flex flex-col gap-4">
                <Hypothesis />
                <div>
                    <Exposures />
                    {!showsHealthPanel && <MultiVariantBiasWarning />}
                </div>
            </div>

            {showRecalculationStatus && <RecalculationStatus experiment={experiment} />}

            {/* Modern metrics view */}
            {!hasMetrics ? (
                <div className="flex flex-col gap-4">
                    {showNoMetricsWarning && (
                        <LemonBanner type="warning">
                            <div>
                                <strong>No metrics defined</strong>
                            </div>
                            <div>
                                Your experiment is running and events are being collected, but no metric is defined. Add
                                at least one metric to see results. Metrics can be added, removed, or changed at any
                                time.
                            </div>
                        </LemonBanner>
                    )}
                    <EmptyMetricsPanel
                        isLaunched={isExperimentLaunched}
                        onAddMetric={(metricType) =>
                            reportNoMetricActedOn(
                                metricType === 'primary' ? 'add_primary_metric' : 'add_secondary_metric'
                            )
                        }
                    />
                </div>
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
    const { experimentLoading, experimentId, experiment, exposureCriteria, showDebugPanel, healthFindings } =
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
                    {healthFindings === null && <ExperimentWarningBanner />}
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
                    <ExperimentMetaBar />
                    <ExperimentHealthPanel />
                    <ExperimentHealthDebug />
                    <ExperimentHeader />
                    <LemonTabs
                        // Fall back to the default tab if the active one is conditionally hidden
                        activeKey={tabs.some((tab) => tab.key === activeTabKey) ? activeTabKey : DEFAULT_EXPERIMENT_TAB}
                        onChange={(key) => setActiveTabKey(key)}
                        // Override sceneInset's -mt-4 pull-up so the tabs keep 32px from whatever sits above them
                        className="mt-4"
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
