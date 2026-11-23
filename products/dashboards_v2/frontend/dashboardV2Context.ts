import { createContext, useContext } from 'react'

import type { DashboardV2Action } from './access/dashboardV2Access'
import type { DashboardEdit } from './layout/dashboardEdits'
import type { Dashboard, DashboardTab } from './layout/dashboardTypes'
import type { DropTarget } from './layout/dropTargets'

/**
 * Everything the dashboard components read and call. A host owns the state and the rules behind it (history, access,
 * saving, the URL) and passes them in, so the components render the same on any page that embeds them.
 */
export interface DashboardV2Controller {
    dashboard: Dashboard
    /** The tab on show, with closed sections already folded. */
    activeTab: DashboardTab
    disabledReasonFor: (action: DashboardV2Action) => string | null
    onEdit: (edit: DashboardEdit) => void
    onActiveTabChange: (tabId: string) => void
    onSectionFoldedChange: (id: string, collapsed: boolean) => void
    /** Told when the canvas gets too narrow for the grid, so the host can refuse edits while it is. */
    onStackedChange?: (stacked: boolean) => void
    /** Left out, the dashboard shows no undo or redo buttons. */
    history?: { canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void }
    dropTarget: DropTarget | null
    onDropTargetChange: (dropTarget: DropTarget | null) => void
}

export type DashboardV2State = Omit<DashboardV2Controller, 'dropTarget' | 'onDropTargetChange'>
export type DashboardV2DragState = Pick<DashboardV2Controller, 'dropTarget' | 'onDropTargetChange'>

// The drop target changes on every cell a dragged tile crosses, so it has its own context: tiles that only read the
// dashboard do not re-render during a drag.
export const DashboardV2StateContext = createContext<DashboardV2State | null>(null)
export const DashboardV2DragContext = createContext<DashboardV2DragState | null>(null)

export function useDashboardV2(): DashboardV2State {
    const state = useContext(DashboardV2StateContext)
    if (!state) {
        throw new Error('useDashboardV2 must be used inside DashboardV2View')
    }
    return state
}

export function useDashboardV2Drag(): DashboardV2DragState {
    const drag = useContext(DashboardV2DragContext)
    if (!drag) {
        throw new Error('useDashboardV2Drag must be used inside DashboardV2View')
    }
    return drag
}
