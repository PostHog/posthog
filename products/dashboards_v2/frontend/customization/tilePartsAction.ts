import type { DashboardEdit } from '../dashboard/dashboardEdits'
import type { ContentWidget } from '../dashboard/dashboardTypes'
import type { TileAction } from '../tiles/TileContextMenu'
import { type ContentWidgetParts, hasPart, showsPart } from './tileParts'

const TILE_PARTS: { key: keyof ContentWidgetParts; label: string }[] = [
    { key: 'header', label: 'Header' },
    { key: 'description', label: 'Description' },
    { key: 'footer', label: 'Footer' },
]

/** The "Show" submenu for a tile, or null when the tile has no parts to choose from. */
export function tilePartsAction(
    id: string,
    widget: ContentWidget,
    disabledReason: string | null,
    onEdit: (edit: DashboardEdit) => void
): TileAction | null {
    const parts = TILE_PARTS.filter(({ key }) => hasPart(widget, key))
    if (parts.length === 0) {
        return null
    }
    return {
        key: 'parts',
        label: 'Show',
        dataAttr: 'dashboard-v2-tile-parts',
        disabledReason,
        submenu: parts.map(({ key, label }) => {
            const shown = showsPart(widget, key)
            const needsHeader = key === 'description' && !showsPart(widget, 'header')
            return {
                key,
                label,
                dataAttr: `dashboard-v2-tile-parts-${key}`,
                // The description lives in the header, so it cannot be turned on while the header is off.
                disabledReason: disabledReason ?? (needsHeader ? 'Show the header first' : null),
                checked: shown,
                onSelect: () => onEdit({ edit: 'setTileParts', id, parts: { ...widget.parts, [key]: !shown } }),
            }
        }),
    }
}
