import { useActions, useValues } from 'kea'
import { useEffect, useMemo } from 'react'

import { FlaggedFeature } from 'lib/components/FlaggedFeature'
import { NotFound } from 'lib/components/NotFound'
import { FEATURE_FLAGS } from 'lib/constants'
import { SceneExport } from 'scenes/sceneTypes'

import { DashboardV2Actions } from './components/DashboardV2Actions'
import { DashboardV2View } from './components/DashboardV2View'
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

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        !!target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor')
    )
}

function DashboardV2(): JSX.Element {
    const { dashboard, activeTab, disabledReasonFor, canUndo, canRedo, dropTarget } = useValues(dashboardV2Logic)
    const { applyDashboardEdit, setActiveTab, setSectionFolded, setStacked, setDropTarget, undo, redo } =
        useActions(dashboardV2Logic)
    const canUndoRedo = disabledReasonFor('undo') === null
    const history = useMemo(() => ({ canUndo, canRedo, onUndo: undo, onRedo: redo }), [canUndo, canRedo, undo, redo])

    useEffect(() => {
        if (!canUndoRedo) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const key = event.key.toLowerCase()
            if (isTyping(event.target) || !(event.metaKey || event.ctrlKey) || (key !== 'z' && key !== 'y')) {
                return
            }
            event.preventDefault()
            if (key === 'y' || event.shiftKey) {
                redo()
            } else {
                undo()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [canUndoRedo, undo, redo])

    return (
        <DashboardV2View
            controller={{
                dashboard,
                activeTab,
                disabledReasonFor,
                onEdit: applyDashboardEdit,
                onActiveTabChange: setActiveTab,
                onSectionFoldedChange: setSectionFolded,
                onStackedChange: setStacked,
                history,
                dropTarget,
                onDropTargetChange: setDropTarget,
            }}
            header={
                <header className="flex flex-wrap items-center justify-between gap-2">
                    <h1 className="text-lg font-semibold m-0">{dashboard.title}</h1>
                    <DashboardV2Actions />
                </header>
            }
        />
    )
}
