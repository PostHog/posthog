import type { ContentWidget, ContentWidgetParts } from '../dashboard/dashboardTypes'
import type { WidgetSlots } from '../widgets/widgetDefinition'

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
