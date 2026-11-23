import { createContext, useContext } from 'react'

import type { DashboardV2Action } from '../access/dashboardV2Access'
import type { DropTarget } from '../grid/dropTargets'
import type { DashboardEdit } from './dashboardEdits'
import type { Dashboard, DashboardTab } from './dashboardTypes'

/**
 * What a host passes to `DashboardV2View`. The host owns the state and the rules behind it (history, access, saving,
 * the URL), so the components render the same on any page that embeds them.
 */
export interface DashboardV2Controller {
    /** The dashboard as shown, with closed sections already folded. */
    dashboard: Dashboard
    /** Unknown or unset shows the first tab. */
    activeTabId: string | null
    disabledReasonFor: (action: DashboardV2Action) => string | null
    onEdit: (edit: DashboardEdit) => void
    onActiveTabChange: (tabId: string) => void
    onSectionFoldedChange: (id: string, collapsed: boolean) => void
    /** Left out, the dashboard shows no undo or redo. */
    history?: { canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void }
}

/** What the components read: the controller, plus what the view works out from it. */
export interface DashboardV2State extends Omit<DashboardV2Controller, 'activeTabId'> {
    activeTab: DashboardTab
    gapPx: number
    can: (action: DashboardV2Action) => boolean
}

export interface DashboardV2DragState {
    dropTarget: DropTarget | null
    setDropTarget: (dropTarget: DropTarget | null) => void
}

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
