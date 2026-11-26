import type { SavedWidget, ContentWidgetParts } from '../dashboard/document/dashboardTypes'
import type { WidgetSlots } from '../widgets/widgetDefinition'

/**
 * Whether a content tile has anything to put in a part. The header has the title and the widget type's header actions.
 * The footer needs something from the widget type.
 */
export function hasPart(widget: SavedWidget, part: keyof ContentWidgetParts, slots: WidgetSlots): boolean {
    switch (part) {
        case 'header':
            return !!widget.title || slots.hasHeader
        case 'footer':
            return slots.hasFooter
    }
}

export function showsPart(widget: SavedWidget, part: keyof ContentWidgetParts): boolean {
    return widget.parts?.[part] !== false
}

export function isPartShown(widget: SavedWidget, part: keyof ContentWidgetParts, slots: WidgetSlots): boolean {
    return hasPart(widget, part, slots) && showsPart(widget, part)
}
