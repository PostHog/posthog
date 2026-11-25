import type { Widget } from '../dashboard/dashboardTypes'
import type { TileAction } from './tileAction'

type TileActionsFilter = (actions: TileAction[], tile: { id: string; widget: Widget }) => TileAction[]

/**
 * Runs the widget type's filter, then the host's. The host goes last so it has the final say on a page, for example to
 * hide an action a widget type added.
 */
export function applyTileActionFilters(
    actions: TileAction[],
    tile: { id: string; widget: Widget },
    widgetFilter: TileActionsFilter | undefined,
    hostFilter: TileActionsFilter | undefined
): TileAction[] {
    const afterWidget = widgetFilter ? widgetFilter(actions, tile) : actions
    return hostFilter ? hostFilter(afterWidget, tile) : afterWidget
}
