import { useActions, useValues } from 'kea'
import { useMountedLogic } from 'kea'

import { LemonBanner, LemonTabs } from '@posthog/lemon-ui'

import { PendingChangeRequestBanner } from 'scenes/approvals/PendingChangeRequestBanner'

import { SceneContent } from '~/layout/scenes/components/SceneContent'

import { experimentLogic } from '../experimentLogic'
import type { ExperimentSceneLogicProps } from '../experimentSceneLogic'
import { experimentSceneLogic } from '../experimentSceneLogic'
import { LoadingState, PageHeaderCustom } from '../ExperimentView/components'
import { DistributionModal, DistributionTable } from '../ExperimentView/DistributionTable'
import { ExperimentWarningBanner } from '../ExperimentView/ExperimentWarningBanners'
import { ReleaseConditionsModal, ReleaseConditionsTable } from '../ExperimentView/ReleaseConditionsTable'
import { LegacyExperimentHeader } from './components/LegacyExperimentHeader'
import { LegacyEditConclusionModal } from './LegacyEditConclusionModal'
import { LegacyExperimentInfo } from './LegacyExperimentInfo'
import { legacyExperimentLogic } from './legacyExperimentLogic'
import { LegacyMetricsView } from './metricsView/LegacyMetricsView'

/**
 * Metrics tab for legacy experiments
 * Shows primary and secondary metrics in read-only mode
 */
const LegacyMetricsTab = (): JSX.Element => {
    return (
        <>
            <LegacyMetricsView isSecondary={false} />
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
    const { setExperiment } = useActions(experimentLogic)
    const { activeTabKey } = useValues(experimentSceneLogic({ tabId }))
    const { setActiveTabKey } = useActions(experimentSceneLogic({ tabId }))

    // Mount legacy logic to handle metrics results loading and archiving
    // This logic is isolated and only handles legacy metric queries
    const legacyLogic = legacyExperimentLogic({
        experiment,
        tabId,
        onExperimentUpdate: (updatedExperiment) => setExperiment(updatedExperiment),
    })
    useMountedLogic(legacyLogic)

    return (
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
                    <LegacyEditConclusionModal />
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
    )
}
