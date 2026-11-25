import type { ContentWidget, ContentWidgetParts } from '../dashboard/dashboardTypes'
import type { TileAction } from '../tiles/tileAction'
import type { WidgetSlots } from '../widgets/widgetDefinition'
import type { PresentationEdit } from './presentationEdits'

/**
 * Whether a content tile has anything to put in a part. The header has the title and the widget type's header actions.
 * The description is a tooltip beside the title, so it needs one. The footer needs something from the widget type.
 */
export function hasPart(widget: ContentWidget, part: keyof ContentWidgetParts, slots: WidgetSlots): boolean {
    switch (part) {
        case 'header':
            return !!widget.title || slots.header
        case 'description':
            return !!widget.title && !!widget.description
        case 'footer':
            return slots.footer
    }
}

/** Whether the person left a part on. The description renders inside the header, so a hidden header hides it too. */
export function showsPart(widget: ContentWidget, part: keyof ContentWidgetParts): boolean {
    return widget.parts?.[part] !== false
}

export function isPartShown(widget: ContentWidget, part: keyof ContentWidgetParts, slots: WidgetSlots): boolean {
    return hasPart(widget, part, slots) && showsPart(widget, part)
}

const TILE_PARTS: { key: keyof ContentWidgetParts; label: string }[] = [
    { key: 'header', label: 'Header' },
    { key: 'description', label: 'Description' },
    { key: 'footer', label: 'Footer' },
]

/** The "Show" submenu for a tile, or null when the tile has no parts to choose from. */
export function tilePartsAction(
    id: string,
    widget: ContentWidget,
    slots: WidgetSlots,
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): TileAction | null {
    const parts = TILE_PARTS.filter(({ key }) => hasPart(widget, key, slots))
    if (parts.length === 0) {
        return null
    }
    return {
        key: 'parts',
        label: 'Show',
        group: 'display',
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
