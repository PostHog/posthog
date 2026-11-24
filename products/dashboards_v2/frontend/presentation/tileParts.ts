import type { ContentWidget, ContentWidgetParts } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import type { WidgetSlots } from '../widgets/widgetDefinition'
import type { PresentationEdit } from './presentationEdits'

/**
 * Whether a content tile has anything to put in a part. The header has the title and the widget type's header actions.
 * The footer needs something from the widget type.
 */
export function hasPart(widget: ContentWidget, part: keyof ContentWidgetParts, slots: WidgetSlots): boolean {
    switch (part) {
        case 'header':
            return !!widget.title || slots.header
        case 'footer':
            return slots.footer
    }
}

export function showsPart(widget: ContentWidget, part: keyof ContentWidgetParts): boolean {
    return widget.parts?.[part] !== false
}

export function isPartShown(widget: ContentWidget, part: keyof ContentWidgetParts, slots: WidgetSlots): boolean {
    return hasPart(widget, part, slots) && showsPart(widget, part)
}

const TILE_PARTS: { key: keyof ContentWidgetParts; label: string }[] = [
    { key: 'header', label: 'Header' },
    { key: 'footer', label: 'Footer' },
]

/** The "Show" submenu for a tile, or null when the tile has no parts to choose from. */
export function tilePartsAction(
    id: string,
    widget: ContentWidget,
    slots: WidgetSlots,
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction | null {
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
            return {
                key,
                label,
                dataAttr: `dashboard-v2-tile-parts-${key}`,
                disabledReason,
                checked: shown,
                onSelect: () => onEdit({ edit: 'setTileParts', id, parts: { ...widget.parts, [key]: !shown } }),
            }
        }),
    }
}
