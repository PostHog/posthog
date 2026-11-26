import { useActions, useValues } from 'kea'
import { useCallback, useMemo, useState } from 'react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { SceneExport } from 'scenes/sceneTypes'
import { teamLogic } from 'scenes/teamLogic'

import { DashboardV2Actions } from './dashboard/DashboardV2Actions'
import type { DashboardV2Controller } from './dashboard/dashboardV2Context'
import { DashboardV2View } from './dashboard/DashboardV2View'
import type { MenuAction } from './dashboard/menuAction'
import { dashboardV2Logic } from './dashboardV2Logic'
import { createQueryBatchRunner } from './data/queryBatchRunner'
import { runSampleQuery } from './fixtures/runSampleQuery'
import { ImportDashboardDialog } from './import/ImportDashboardDialog'
import { createChartPanel } from './panels/chart/createChartPanel'
import { DEFAULT_PANELS } from './panels/defaultPanels'

const NON_CHART_PANELS = DEFAULT_PANELS.filter((panel) => panel.type !== 'chart')
const SAMPLE_PANELS = [createChartPanel({ runQuery: runSampleQuery }), ...NON_CHART_PANELS]

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
    const { applyDashboardEdit, setActiveTab, undo, redo, openDashboard } = useActions(dashboardV2Logic)
    const [importing, setImporting] = useState(false)
    const { featureFlags } = useValues(featureFlagLogic)
    const { currentTeamId } = useValues(teamLogic)
    // The same pair of flags as the v1 dashboard query layer: the project turns it on, the person sees it.
    const runsRealQueries =
        !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2] &&
        !!featureFlags[FEATURE_FLAGS.DASHBOARD_V2_USERS] &&
        !!currentTeamId
    // The chart cache is keyed by runner, so a runner per visit drops results checked against this person's access
    // when they leave, instead of showing them again after their access changes.
    const panels = useMemo(
        () =>
            runsRealQueries && currentTeamId
                ? [createChartPanel({ runQuery: createQueryBatchRunner(currentTeamId) }), ...NON_CHART_PANELS]
                : SAMPLE_PANELS,
        [runsRealQueries, currentTeamId]
    )
    const dashboardActions = useCallback(
        (actions: MenuAction[]): MenuAction[] => [
            {
                key: 'import',
                label: 'Import from Grafana or New Relic',
                dataAttr: 'dashboard-v2-import-open-dialog',
                // Without real queries, charts show sample numbers, which would pass as the imported board's own.
                disabledReason: runsRealQueries
                    ? disabledReasonFor('addTab')
                    : 'Importing needs live queries, which are not on for you yet',
                onSelect: () => setImporting(true),
                group: 'dashboard',
            },
            ...actions,
        ],
        [disabledReasonFor, runsRealQueries]
    )
    const controller = useMemo<DashboardV2Controller>(
        () => ({
            dashboard,
            activeTabId,
            panels,
            disabledReasonFor,
            onEdit: applyDashboardEdit,
            onActiveTabChange: setActiveTab,
            history: { canUndo, canRedo, onUndo: undo, onRedo: redo },
            refresh: {},
            dashboardActions,
        }),
        [
            dashboardActions,
            dashboard,
            activeTabId,
            panels,
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
        <>
            <ImportDashboardDialog open={importing} onClose={() => setImporting(false)} onOpenBoard={openDashboard} />
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
        </>
    )
}
