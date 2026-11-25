import './DashboardV2.scss'

import { type ReactNode, type RefObject, useCallback, useEffect, useMemo, useState } from 'react'
import { useContainerWidth } from 'react-grid-layout'

import type { DashboardV2Action } from '../access/dashboardV2Access'
import type { DropTarget } from '../grid/dropTargets'
import { GridDragContext, type GridDragState } from '../grid/gridDrag'
import { stackTiles } from '../grid/gridTiles'
import { TileMountContext, createTileMountScheduler } from '../grid/tileMounting'
import { DashboardTileGrid } from '../tiles/DashboardTileGrid'
import { DEFAULT_TIME_RANGE, TimeRangeContext } from '../widgets/timeRangeContext'
import { sizeOfWidgets } from '../widgets/widgetSpec'
import { withFolds } from './dashboardEdits'
import { type Dashboard, GRID, activeGridTab } from './dashboardTypes'
import { type DashboardV2Controller, type DashboardV2State, DashboardV2StateContext } from './dashboardV2Context'
import { DashboardV2Tabs } from './DashboardV2Tabs'

const STACKED_REASON = 'Open this dashboard on a wider screen to edit it'

export interface DashboardV2ViewProps {
    controller: DashboardV2Controller
    /** Rendered above the tabs, inside the dashboard, so it can use the dashboard's own controls. */
    header?: ReactNode
}

function isTyping(target: EventTarget | null): boolean {
    return (
        target instanceof Element &&
        !!target.closest('input, textarea, select, [contenteditable="true"], .monaco-editor')
    )
}

/** A whole dashboard: tabs and grid. Its own state is only what the screen and a drag in progress decide. */
export function DashboardV2View({ controller, header }: DashboardV2ViewProps): JSX.Element {
    const { width, containerRef, mounted } = useContainerWidth()
    const stacked = width > 0 && width < GRID.stackBelowPx
    const [dropTarget, setDropTarget] = useState<DropTarget | null>(null)
    const sizeOf = useMemo(() => sizeOfWidgets(controller.widgets), [controller.widgets])
    // Which sections this person opened or closed. Only the screen needs it, so the host never sees it.
    const [folds, setFolds] = useState<Record<string, boolean>>({})
    const onSectionFoldedChange = useCallback(
        (id: string, collapsed: boolean) => setFolds((previous) => ({ ...previous, [id]: collapsed })),
        []
    )

    const state = useMemo<DashboardV2State>(() => {
        const { activeTabId, disabledReasonFor: hostReason, onEdit: hostOnEdit, ...rest } = controller
        const disabledReasonFor = (action: DashboardV2Action): string | null =>
            hostReason(action) ?? (stacked ? STACKED_REASON : null)
        const view = (dashboard: Dashboard): Dashboard => withFolds(dashboard, folds, sizeOf)
        const dashboard = view(rest.dashboard)
        return {
            ...rest,
            dashboard,
            activeTab: activeGridTab(dashboard, activeTabId),
            sizeOf,
            disabledReasonFor,
            can: (action) => disabledReasonFor(action) === null,
            onEdit: (edit) => hostOnEdit(edit, view),
            onSectionFoldedChange,
        }
    }, [controller, stacked, sizeOf, folds, onSectionFoldedChange])
    const drag = useMemo<GridDragState>(() => ({ dropTarget, setDropTarget }), [dropTarget])
    const [mountScheduler] = useState(createTileMountScheduler)
    useEffect(() => () => mountScheduler.dispose(), [mountScheduler])

    const { activeTab, can, history } = state
    const tiles = useMemo(
        () => (stacked ? stackTiles(activeTab.tiles, GRID.columns, sizeOf) : activeTab.tiles),
        [stacked, activeTab.tiles, sizeOf]
    )

    const undoable = can('undo') ? history : undefined
    useEffect(() => {
        if (!undoable) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const key = event.key.toLowerCase()
            if (isTyping(event.target) || !(event.metaKey || event.ctrlKey) || (key !== 'z' && key !== 'y')) {
                return
            }
            event.preventDefault()
            if (key === 'y' || event.shiftKey) {
                if (can('redo')) {
                    undoable.onRedo()
                }
            } else {
                undoable.onUndo()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [undoable, can])

    return (
        <DashboardV2StateContext.Provider value={state}>
            <GridDragContext.Provider value={drag}>
                <TimeRangeContext.Provider value={controller.dashboard.time ?? DEFAULT_TIME_RANGE}>
                    <TileMountContext.Provider value={mountScheduler}>
                        <div
                            data-quill
                            className="DashboardV2 flex flex-col gap-4 p-4 min-h-full bg-background text-foreground"
                        >
                            {header}
                            <DashboardV2Tabs />
                            <div ref={containerRef as RefObject<HTMLDivElement>} className="DashboardV2__canvas">
                                {mounted && width > 0 && (
                                    <DashboardTileGrid
                                        key={`${activeTab.id}-${stacked ? 'stacked' : 'grid'}`}
                                        gridId={activeTab.id}
                                        tiles={tiles}
                                        cols={GRID.columns}
                                        width={width}
                                        editable={can('placeTiles')}
                                    />
                                )}
                            </div>
                        </div>
                    </TileMountContext.Provider>
                </TimeRangeContext.Provider>
            </GridDragContext.Provider>
        </DashboardV2StateContext.Provider>
    )
}
