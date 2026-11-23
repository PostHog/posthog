import './DashboardV2.scss'

import { type CSSProperties, type ReactNode, type RefObject, useEffect, useMemo, useState } from 'react'
import { useContainerWidth } from 'react-grid-layout'

import type { DashboardV2Action } from '../access/dashboardV2Access'
import { gapPxOf } from '../customization/tileSpacing'
import type { DropTarget } from '../grid/dropTargets'
import { TileGrid } from '../grid/TileGrid'
import { stackTiles } from './dashboardEdits'
import { GRID } from './dashboardTypes'
import {
    type DashboardV2Controller,
    DashboardV2DragContext,
    type DashboardV2DragState,
    type DashboardV2State,
    DashboardV2StateContext,
} from './dashboardV2Context'
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

    const state = useMemo<DashboardV2State>(() => {
        const { activeTabId, disabledReasonFor: hostReason, ...rest } = controller
        const disabledReasonFor = (action: DashboardV2Action): string | null =>
            hostReason(action) ?? (stacked ? STACKED_REASON : null)
        return {
            ...rest,
            activeTab: rest.dashboard.tabs.find((tab) => tab.id === activeTabId) ?? rest.dashboard.tabs[0],
            gapPx: gapPxOf(rest.dashboard),
            disabledReasonFor,
            can: (action) => disabledReasonFor(action) === null,
        }
    }, [controller, stacked])
    const drag = useMemo<DashboardV2DragState>(() => ({ dropTarget, setDropTarget }), [dropTarget])

    const { activeTab, gapPx, can, history } = state
    const tiles = useMemo(
        () => (stacked ? stackTiles(activeTab.tiles, GRID.columns) : activeTab.tiles),
        [stacked, activeTab.tiles]
    )

    const canUndoRedo = !!history && can('undo')
    useEffect(() => {
        if (!history || !canUndoRedo) {
            return
        }
        const onKeyDown = (event: KeyboardEvent): void => {
            const key = event.key.toLowerCase()
            if (isTyping(event.target) || !(event.metaKey || event.ctrlKey) || (key !== 'z' && key !== 'y')) {
                return
            }
            event.preventDefault()
            if (key === 'y' || event.shiftKey) {
                history.onRedo()
            } else {
                history.onUndo()
            }
        }
        window.addEventListener('keydown', onKeyDown)
        return () => window.removeEventListener('keydown', onKeyDown)
    }, [history, canUndoRedo])

    return (
        <DashboardV2StateContext.Provider value={state}>
            <DashboardV2DragContext.Provider value={drag}>
                <div
                    data-quill
                    className="DashboardV2 flex flex-col gap-4 p-4 min-h-full bg-background text-foreground"
                    // The tile gap comes from the dashboard's JSON, so CSS reads it from a variable rather than a class.
                    // oxlint-disable-next-line react/forbid-dom-props
                    style={{ '--dv2-gap': `${gapPx}px` } as CSSProperties}
                >
                    {header}
                    <DashboardV2Tabs />
                    <div ref={containerRef as RefObject<HTMLDivElement>} className="DashboardV2__canvas">
                        {mounted && width > 0 && (
                            <TileGrid
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
            </DashboardV2DragContext.Provider>
        </DashboardV2StateContext.Provider>
    )
}
