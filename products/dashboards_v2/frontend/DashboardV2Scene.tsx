import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import { DashboardV2Actions } from './components/DashboardV2Actions'
import { DashboardV2View } from './components/DashboardV2View'
import type { DashboardV2Controller } from './dashboardV2Context'
import { dashboardV2Logic } from './dashboardV2Logic'

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
    const { viewedDashboard, activeTabId, disabledReasonFor, canUndo, canRedo } = useValues(dashboardV2Logic)
    const { applyDashboardEdit, setActiveTab, setSectionFolded, undo, redo } = useActions(dashboardV2Logic)
    const controller = useMemo<DashboardV2Controller>(
        () => ({
            dashboard: viewedDashboard,
            activeTabId,
            disabledReasonFor,
            onEdit: applyDashboardEdit,
            onActiveTabChange: setActiveTab,
            onSectionFoldedChange: setSectionFolded,
            history: { canUndo, canRedo, onUndo: undo, onRedo: redo },
        }),
        [
            viewedDashboard,
            activeTabId,
            disabledReasonFor,
            applyDashboardEdit,
            setActiveTab,
            setSectionFolded,
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
                    <h1 className="text-lg font-semibold m-0">{viewedDashboard.title}</h1>
                    <DashboardV2Actions />
                </header>
            }
        />
    )
}
