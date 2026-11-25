import { useActions, useValues } from 'kea'
import { useMemo, useRef } from 'react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardActions } from '../dashboard/DashboardActions'
import type { DashboardController } from '../dashboard/dashboardContext'
import { DashboardView } from '../dashboard/DashboardView'
import { createQueryBatchRunner } from '../data/queryBatchRunner'
import { ANALYTICS_FILTER_TYPES } from '../filters/analytics/analyticsFilterTypes'
import { useDashboardFilters } from '../filters/useDashboardFilters'
import { runSampleQuery } from '../fixtures/runSampleQuery'
import { createChartWidget } from '../widgets/chart/createChartWidget'
import { DEFAULT_WIDGETS } from '../widgets/defaultWidgets'
import { dashboardSceneLogic } from './dashboardSceneLogic'

const NON_CHART_WIDGETS = DEFAULT_WIDGETS.filter((widget) => widget.type !== 'chart')
const SAMPLE_WIDGETS = [createChartWidget({ runQuery: runSampleQuery }), ...NON_CHART_WIDGETS]

export const scene: SceneExport = {
    component: DashboardScene,
    logic: dashboardSceneLogic,
}

export function DashboardScene(): JSX.Element {
    return (
        <FlaggedFeature flag={FEATURE_FLAGS.DASHBOARDS_V2} fallback={<NotFound object="page" />}>
            <DashboardV2 />
        </FlaggedFeature>
    )
}

function DashboardV2(): JSX.Element {
    const { dashboard, activeTabId, disabledReasonFor, canUndo, canRedo } = useValues(dashboardSceneLogic)
    const { applyDashboardEdit, setActiveTab, undo, redo } = useActions(dashboardSceneLogic)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId, timezone } = useValues(teamLogic)
    const tabRef = useRef(activeTabId)
    tabRef.current = activeTabId
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
                ? [
                      createChartWidget({
                          runQuery: createQueryBatchRunner(currentTeamId, {
                              context: () => ({ dashboard_tab_id: tabRef.current }),
                          }),
                      }),
                      ...NON_CHART_WIDGETS,
                  ]
                : SAMPLE_WIDGETS,
        [runsRealQueries, currentTeamId]
    )
    // TODO(2026-11-25): Offer filters with real queries once the query batch request carries them; until then only the
    // sample runner applies them, so a filter bar there would narrow nothing.
    const { filters, timeRange } = useDashboardFilters({
        types: runsRealQueries ? undefined : ANALYTICS_FILTER_TYPES,
        time: { timezone },
    })
    const controller = useMemo<DashboardController>(
        () => ({
            dashboard,
            activeTabId,
            widgets,
            disabledReasonFor,
            onEdit: applyDashboardEdit,
            onActiveTabChange: setActiveTab,
            history: { canUndo, canRedo, onUndo: undo, onRedo: redo },
            refresh: {},
            filters,
            timeRange,
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
            filters,
            timeRange,
        ]
    )

    return (
        <DashboardView
            controller={controller}
            header={
                <header className="flex flex-wrap items-center justify-between gap-2">
                    <div className="flex flex-col gap-1 min-w-0">
                        <h1 className="text-lg font-semibold m-0">{dashboard.title}</h1>
                        {dashboard.description && (
                            <p className="text-sm text-muted-foreground m-0">{dashboard.description}</p>
                        )}
                    </div>
                    <DashboardActions />
                </header>
            }
        />
    )
}
