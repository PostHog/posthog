import { createContext, useContext } from 'react'

import type { TimeRangeController } from '../../filters/time/useTimeRangeController'
import type { FiltersController } from '../../filters/useFiltersController'
import type { MenuAction } from '../../menu/menuAction'
import type { PanelType } from '../../panels/core/panelDefinition'
import { type SizeOf } from '../../panels/core/panelSpec'
import type { AutoRefreshProps } from '../actions/AutoRefreshButton'
import type { ImageFormat } from '../actions/dashboardImage'
import type { Dashboard, GridTab, Panel } from '../document/dashboardTypes'
import type { DashboardEdit, View } from '../edits/dashboardEdits'

/** Everything a person can do to a dashboard. A host's `disabledReasonFor` can give each one its own answer. */
export type DashboardAction = DashboardEdit['edit'] | 'undo' | 'redo'

/**
 * What a host passes to `DashboardView`. The host owns the state and the rules behind it (history, access, saving,
 * the URL), so the components render the same on any page that embeds them.
 */
export type DashboardController = {
    /** The saved dashboard. The view folds closed sections itself. */
    dashboard: Dashboard
    /** Unknown or unset shows the first tab. Without `onActiveTabChange`, it is only the tab shown first. */
    activeTabId?: string | null
    /** The panel types this dashboard can show and add. Keep the array stable between renders, or every tile re-renders. */
    panels: PanelType[]
    disabledReasonFor?: (action: DashboardAction) => string | null
    /**
     * Called with each edit, and with how the person saw the dashboard when they made it. Pass `view` to `applyEdit`,
     * so a tile lands where the person dropped it in a layout with closed sections. Left out, the dashboard is read-only.
     */
    onEdit?: (edit: DashboardEdit, view: View) => void
    /** Left out, the dashboard keeps the shown tab itself, such as for a dashboard with no URL of its own. */
    onActiveTabChange?: (tabId: string) => void
    /**
     * Receives what a content tile or a section does to itself, after the panel type's own changes, and returns the
     * list to show. Lets a page hide, disable or add actions by `MenuAction.key`, such as `chart-type`.
     */
    tileActions?: (actions: MenuAction[], tile: { id: string; panel: Panel }) => MenuAction[]
    /**
     * Receives what a person can do to where a tile or a section sits on the dashboard, and returns the list to show.
     * Lets a page hide, disable or add actions by `MenuAction.key`, such as `remove`.
     */
    tilePlacementActions?: (actions: MenuAction[], tile: { id: string; panel: Panel }) => MenuAction[]
    dashboardActions?: (actions: MenuAction[]) => MenuAction[]
    /**
     * Left out, the dashboard shows no refresh button. Each refresh, from the button or the interval picked there, runs
     * every chart's query again, and calls `onRefresh` for anything else the host reloads.
     */
    refresh?: RefreshController
    /**
     * Left out, the dashboard has no filters. With it, an editor can allow filters on the dashboard, and then add any of
     * `types`. A host adds its own kinds of filter to `types`. Each viewer's picked values live with the host, such as in
     * the URL, and are never saved with the dashboard.
     * `useFiltersController` keeps them in component state.
     */
    filters?: FiltersController
    /**
     * Left out, the dashboard shows its saved range with no picker. With it, a viewer picks a range that overrides the
     * saved one and is never saved. `useTimeRangeController` keeps it in component state.
     */
    timeRange?: TimeRangeController
    /** Left out, the dashboard shows no undo or redo. */
    history?: { canUndo: boolean; canRedo: boolean; onUndo: () => void; onRedo: () => void }
}

export type RefreshController = {
    /** The interval choices besides off, in seconds. */
    intervals?: number[]
    /** In seconds. Left out, auto refresh starts off. */
    initialInterval?: number | null
    refreshing?: boolean
    onRefresh?: () => void
}

/** What the components read: the controller, plus what the view works out from it. */
export type DashboardState = Omit<
    DashboardController,
    'activeTabId' | 'onEdit' | 'refresh' | 'disabledReasonFor' | 'onActiveTabChange'
> & {
    refresh?: AutoRefreshProps
    /** The dashboard as this person sees it, with the sections they closed folded. */
    dashboard: Dashboard
    onEdit: (edit: DashboardEdit) => void
    onActiveTabChange: (tabId: string) => void
    disabledReasonFor: (action: DashboardAction) => string | null
    /** Opens or closes a section for this person only. It is not saved and is not an undo step. */
    onSectionFoldedChange: (id: string, collapsed: boolean) => void
    activeTab: GridTab
    sizeOf: SizeOf
    can: (action: DashboardAction) => boolean
    /** Downloads the tab on screen, or with `tileId`, just that tile. */
    downloadImage: (format: ImageFormat, tileId?: string) => void
    downloadingImage: boolean
    /** The tile shown on its own over the dashboard, or null. Only the screen keeps it. */
    slideshowTileId: string | null
    showSlideshow: (id: string | null) => void
}

export const DashboardStateContext = createContext<DashboardState | null>(null)

export function useDashboard(): DashboardState {
    const state = useContext(DashboardStateContext)
    if (!state) {
        throw new Error('useDashboard must be used inside DashboardView')
    }
    return state
}
