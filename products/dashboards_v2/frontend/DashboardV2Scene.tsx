import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import { DashboardV2Actions } from './dashboard/DashboardV2Actions'
import type { DashboardV2Controller } from './dashboard/dashboardV2Context'
import { DashboardV2View } from './dashboard/DashboardV2View'
import { dashboardV2Logic } from './dashboardV2Logic'
import { runSampleQuery } from './fixtures/runSampleQuery'
import { createChartWidget } from './widgets/chart/createChartWidget'
import { DEFAULT_WIDGETS } from './widgets/defaultWidgets'

// The default widgets, with charts drawn from sample data until the scene runs real queries.
const SCENE_WIDGETS = [
    createChartWidget({ runQuery: runSampleQuery }),
    ...DEFAULT_WIDGETS.filter((widget) => widget.type !== 'chart'),
]

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
    const controller = useMemo<DashboardV2Controller>(
        () => ({
            dashboard,
            activeTabId,
            widgets: SCENE_WIDGETS,
            disabledReasonFor,
            onEdit: applyDashboardEdit,
            onActiveTabChange: setActiveTab,
            history: { canUndo, canRedo, onUndo: undo, onRedo: redo },
        }),
        [dashboard, activeTabId, disabledReasonFor, applyDashboardEdit, setActiveTab, canUndo, canRedo, undo, redo]
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
