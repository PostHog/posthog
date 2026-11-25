import { createContext, useContext } from 'react'

import type { DashboardV2Action } from '../access/dashboardV2Access'
import type { TileAction } from '../tiles/tileAction'
import type { WidgetDefinition } from '../widgets/widgetDefinition'
import type { DashboardEdit, View } from './dashboardEdits'
import type { Dashboard, GridTab, SizeOf, Widget } from './dashboardTypes'

/**
 * What a host passes to `DashboardV2View`. The host owns the state and the rules behind it (history, access, saving,
 * the URL), so the components render the same on any page that embeds them.
 */
export interface DashboardV2Controller {
    /** The saved dashboard. The view folds closed sections itself. */
    dashboard: Dashboard
    /** Unknown or unset shows the first tab. */
    activeTabId: string | null
    /** The widget types this dashboard can show and add. Keep the array stable between renders, or every tile re-renders. */
    widgets: WidgetDefinition[]
    disabledReasonFor: (action: DashboardV2Action) => string | null
    /**
     * Called with each edit, and with how the person saw the dashboard when they made it. Pass `view` to `applyEdit`,
     * so a tile lands where the person dropped it in a layout with closed sections.
     */
    onEdit: (edit: DashboardEdit, view: View) => void
    onActiveTabChange: (tabId: string) => void
    /**
     * Receives the full right-click action list of a content tile or a section, after the widget type's own changes, and
     * returns the list to show. Lets a page hide, disable or add actions by `TileAction.key`, such as `remove`.
     */
    tileActions?: (actions: TileAction[], tile: { id: string; widget: Widget }) => TileAction[]
    /** Left out, the dashboard shows no undo or redo. */
    history?: { canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void }
}

/** What the components read: the controller, plus what the view works out from it. */
export interface DashboardV2State extends Omit<DashboardV2Controller, 'activeTabId' | 'onEdit'> {
    /** The dashboard as this person sees it, with the sections they closed folded. */
    dashboard: Dashboard
    onEdit: (edit: DashboardEdit) => void
    /** Opens or closes a section for this person only. It is not saved and is not an undo step. */
    onSectionFoldedChange: (id: string, collapsed: boolean) => void
    activeTab: GridTab
    sizeOf: SizeOf
    can: (action: DashboardV2Action) => boolean
}

export const DashboardV2StateContext = createContext<DashboardV2State | null>(null)

export function useDashboardV2(): DashboardV2State {
    const state = useContext(DashboardV2StateContext)
    if (!state) {
        throw new Error('useDashboardV2 must be used inside DashboardV2View')
    }
    return state
}
