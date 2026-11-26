import type { Panel } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'

type TileActionsFilter = (actions: MenuAction[], tile: { id: string; panel: Panel }) => MenuAction[]

/**
 * Runs the panel type's filter, then the host's. The host goes last so it has the final say on a page, for example to
 * hide an action a panel type added.
 */
export function applyTileActionFilters(
    actions: MenuAction[],
    tile: { id: string; panel: Panel },
    panelFilter: TileActionsFilter | undefined,
    hostFilter: TileActionsFilter | undefined
): MenuAction[] {
    const afterPanel = panelFilter ? panelFilter(actions, tile) : actions
    return hostFilter ? hostFilter(afterPanel, tile) : afterPanel
}
