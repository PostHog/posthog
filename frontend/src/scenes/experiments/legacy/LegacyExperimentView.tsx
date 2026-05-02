import { BindLogic, useActions, useMountedLogic, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'

import { SceneContent } from '~/layout/scenes/components/SceneContent'
import {
    ExperimentFunnelsQuery,
    ExperimentTrendsQuery,
    ExperimentTrendsQueryResponse,
    ExperimentFunnelsQueryResponse,
} from '~/queries/schema/schema-general'
import {
    LegacyExperimentHeader,
    LegacyExperimentInfo,
    LegacyMetricsView,
    legacyExperimentLogic,
    LegacyOverview,
    LegacySummaryTable,
    LegacyResultsQuery,
    LegacyExploreButton,
} from '~/scenes/experiments/legacy'
import { Experiment } from '~/types'

import { experimentLogic } from '../experimentLogic'
import type { ExperimentSceneLogicProps } from '../experimentSceneLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { LoadingState, PageHeaderCustom } from '../ExperimentView/components'
import { DistributionModal, DistributionTable } from '../ExperimentView/DistributionTable'
import { ExperimentWarningBanner } from '../ExperimentView/ExperimentWarningBanners'
import { ReleaseConditionsModal, ReleaseConditionsTable } from '../ExperimentView/ReleaseConditionsTable'

const getFirstPrimaryMetric = (experiment: Experiment): ExperimentTrendsQuery | ExperimentFunnelsQuery | null => {
    if (experiment.metrics.length) {
        return experiment.metrics[0] as ExperimentTrendsQuery | ExperimentFunnelsQuery
    }
    const primaryMetric = experiment.saved_metrics.find((metric) => metric.metadata.type === 'primary')
    if (primaryMetric) {
        return primaryMetric.query as ExperimentTrendsQuery | ExperimentFunnelsQuery
    }
    return null
}
/**
 * Metrics tab for legacy experiments
 * Shows primary and secondary metrics in read-only mode
 */
const LegacyMetricsTab = (): JSX.Element => {
    const { experiment, legacyPrimaryMetricsResults } = useValues(legacyExperimentLogic)

    const firstPrimaryMetric = getFirstPrimaryMetric(experiment)

    const hasSomeResults = legacyPrimaryMetricsResults?.some((result) => result?.insight)
    const primaryMetricsLengthWithSharedMetrics =
        experiment.metrics.length +
        experiment.saved_metrics.filter((metric) => metric.metadata.type === 'primary').length
    const hasSinglePrimaryMetric = primaryMetricsLengthWithSharedMetrics === 1
    const firstPrimaryMetricResult = legacyPrimaryMetricsResults?.[0]

    /**
     * Show a detailed results if:
     * - there's a single primary metric
     * - if the metric has insight results
     * - if we have the minimum number of exposures
     * - if it's the first primary metric (?)
     *
     * this is only for legacy experiments.
     */
    const showResultDetails = hasSomeResults && hasSinglePrimaryMetric && firstPrimaryMetric && firstPrimaryMetricResult

    return (
        <>
            {hasSinglePrimaryMetric && (
                <div className="mb-4 mt-2">
                    <LegacyOverview metricUuid={firstPrimaryMetric?.uuid || ''} />
                </div>
            )}
            <LegacyMetricsView isSecondary={false} />
            {showResultDetails && (
                <>
                    <div className="pb-4">
                        <LegacySummaryTable metric={firstPrimaryMetric} displayOrder={0} isSecondary={false} />
                    </div>
                    <div className="flex justify-end">
                        <LegacyExploreButton
                            result={
                                firstPrimaryMetricResult as
                                    | ExperimentTrendsQueryResponse
                                    | ExperimentFunnelsQueryResponse
                            }
                            size="xsmall"
                        />
                    </div>
                    <div className="pb-4">
                        <LegacyResultsQuery
                            result={
                                firstPrimaryMetricResult as
                                    | ExperimentTrendsQueryResponse
                                    | ExperimentFunnelsQueryResponse
                                    | null
                            }
                            showTable={true}
                        />
                    </div>
                </>
            )}
            <LegacyMetricsView isSecondary={true} />
        </>
    )
}

/**
 * Variants tab showing release conditions and distribution
 */
const VariantsTab = (): JSX.Element => {
    return (
        <div className="deprecated-space-y-8 mt-2">
            <ReleaseConditionsTable />
            <DistributionTable />
        </div>
    )
}

/**
 * Legacy experiment view component
 *
 * This component handles experiments that use the legacy query format
 * (ExperimentTrendsQuery/ExperimentFunnelsQuery). These experiments are
 * frozen and cannot be edited - they can only be viewed.
 *
 * Key differences from modern experiments:
 * - No Settings tab
 * - No AI Analysis tab
 * - No Code tab
 * - No History tab
 * - No User Feedback tab
 * - No metric editing (read-only metrics)
 * - No exposure criteria editing
 * - Uses legacy metrics view and calculations
 *
 * Only includes the minimal set of tabs needed to view legacy experiment results:
 * - Metrics (primary and secondary, read-only)
 * - Variants (distribution and release conditions)
 *
 * @deprecated This component exists only to support existing legacy experiments.
 * New experiments use the modern ExperimentView component.
 */
export function LegacyExperimentView({ tabId }: Pick<ExperimentSceneLogicProps, 'tabId'>): JSX.Element {
    if (!tabId) {
        throw new Error('<LegacyExperimentView /> must receive a tabId prop')
    }

    const { experimentLoading, experiment } = useValues(experimentLogic)
    const { activeTabKey } = useValues(experimentSceneLogic({ tabId }))
    const { setActiveTabKey } = useActions(experimentSceneLogic({ tabId }))

    // Props for legacy logic - uses experiment data from parent experimentLogic
    const legacyLogicProps = {
        experiment,
        tabId,
    }

    // Mount the logic and load metrics when experiment is available
    const logic = legacyExperimentLogic(legacyLogicProps)
    useMountedLogic(logic)
    const { refreshExperimentResults } = useActions(logic)

    // Load metrics on mount - afterMount doesn't fire reliably on reconnections
    useEffect(() => {
        if (!experimentLoading && experiment) {
            refreshExperimentResults(false, 'page_load')
        }
    }, [experimentLoading, experiment?.id])

    return (
        <BindLogic logic={legacyExperimentLogic} props={legacyLogicProps}>
            <SceneContent>
                <PageHeaderCustom />
                {experimentLoading ? (
                    <LoadingState />
                ) : (
                    <>
                        <ExperimentWarningBanner />

                        {/* Warning banner indicating this is a legacy experiment */}
                        <LemonBanner type="warning" className="mb-4">
                            This is a legacy experiment. Metrics can no longer be edited.
                        </LemonBanner>

                        {/* Show pending change request banner if there's one for the feature flag */}
                        {experiment.feature_flag?.id && (
                            <PendingChangeRequestBanner
                                resourceType="feature_flag"
                                resourceId={experiment.feature_flag.id}
                                context="experiment"
                            />
                        )}

                        {/* Legacy experiment info and header */}
                        <LegacyExperimentInfo />
                        <LegacyExperimentHeader />

                        {/* Tab navigation - only includes minimal tabs for legacy experiments */}
                        <LemonTabs
                            activeKey={activeTabKey}
                            onChange={(key) => setActiveTabKey(key)}
                            sceneInset
                            tabs={[
                                {
                                    key: 'metrics',
                                    label: 'Metrics',
                                    content: <LegacyMetricsTab />,
                                },
                                {
                                    key: 'variants',
                                    label: 'Variants',
                                    content: <VariantsTab />,
                                },
                            ]}
                        />

                        {/* Modals that legacy experiments support */}
                        <DistributionModal />
                        <ReleaseConditionsModal />

                        {/* Legacy experiments do NOT support these modals:
                          - MetricSourceModal (can't add metrics)
                          - ExperimentMetricModal (can't edit metrics)
                          - SharedMetricModal (can't add shared metrics)
                          - SharedMetricDetailsModal (can't manage shared metrics)
                          - ExposureCriteriaModal (can't edit exposure)
                          - RunningTimeCalculatorModal (modern feature)
                          - EditConclusionModal (uses legacy version instead)
                        */}
                    </>
                )}
            </SceneContent>
        </BindLogic>
    )
}
