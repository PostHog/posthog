import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardV2Actions } from './dashboard/DashboardV2Actions'
import type { DashboardV2Controller } from './dashboard/dashboardV2Context'
import { DashboardV2View } from './dashboard/DashboardV2View'
import { dashboardV2Logic } from './dashboardV2Logic'
import { createQueryBatchRunner } from './data/queryBatchRunner'
import { runSampleQuery } from './fixtures/runSampleQuery'
import { createChartWidget } from './widgets/chart/createChartWidget'
import { DEFAULT_WIDGETS } from './widgets/defaultWidgets'

const NON_CHART_WIDGETS = DEFAULT_WIDGETS.filter((widget) => widget.type !== 'chart')
const SAMPLE_WIDGETS = [createChartWidget({ runQuery: runSampleQuery }), ...NON_CHART_WIDGETS]

export const scene: SceneExport = {
    component: DashboardV2Scene,
    logic: dashboardV2Logic,
}

export function DashboardV2Scene(): JSX.Element {
    return (
        <FlaggedFeature flag={FEATURE_FLAGS.DASHBOARDS_V2} fallback={<NotFound object="page" />}>
            <DashboardV2 />
        </FlaggedFeature>
    )
}

function DashboardV2(): JSX.Element {
    const { dashboard, activeTabId, disabledReasonFor, canUndo, canRedo } = useValues(dashboardV2Logic)
    const { applyDashboardEdit, setActiveTab, undo, redo } = useActions(dashboardV2Logic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    // The same pair of flags as the v1 dashboard query layer: the project turns it on, the person sees it.
    const runsRealQueries =
        !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2] &&
        !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2_USERS] &&
        !!currentTeamId
    // The chart cache is keyed by runner, so a runner per visit drops results checked against this person's access
    // when they leave, instead of showing them again after their access changes.
    const widgets = useMemo(
        () =>
            runsRealQueries && currentTeamId
                ? [createChartWidget({ runQuery: createQueryBatchRunner(currentTeamId) }), ...NON_CHART_WIDGETS]
                : SAMPLE_WIDGETS,
        [runsRealQueries, currentTeamId]
    )
    const controller = useMemo<DashboardV2Controller>(
        () => ({
            dashboard,
            activeTabId,
            widgets,
            disabledReasonFor,
            onEdit: applyDashboardEdit,
            onActiveTabChange: setActiveTab,
            history: { canUndo, canRedo, onUndo: undo, onRedo: redo },
            refresh: {},
        }),
        [
            dashboard,
            activeTabId,
            widgets,
            disabledReasonFor,
            applyDashboardEdit,
            setActiveTab,
            canUndo,
            canRedo,
            undo,
            redo,
        ]
    )

    return (
        <DashboardV2View
            controller={controller}
            header={
                <header className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-1 min-w-0">
                        <h1 className="text-lg font-semibold m-0">{dashboard.title}</h1>
                        {dashboard.description && (
                            <p className="text-sm text-muted-foreground m-0">{dashboard.description}</p>
                        )}
                    </div>
                    <DashboardV2Actions />
                </header>
            }
        />
    )
}
