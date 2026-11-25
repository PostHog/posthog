import type { Widget } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'

type TileActionsFilter = (actions: MenuAction[], tile: { id: string; widget: Widget }) => MenuAction[]

/**
 * Runs the widget type's filter, then the host's. The host goes last so it has the final say on a page, for example to
 * hide an action a widget type added.
 */
export function applyTileActionFilters(
    actions: MenuAction[],
    tile: { id: string; widget: Widget },
    widgetFilter: TileActionsFilter | undefined,
    hostFilter: TileActionsFilter | undefined
): MenuAction[] {
    const afterWidget = widgetFilter ? widgetFilter(actions, tile) : actions
    return hostFilter ? hostFilter(afterWidget, tile) : afterWidget
}
