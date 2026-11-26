import type { ContentPanel, ContentPanelParts } from '../dashboard/dashboardTypes'
import type { PanelSlots } from '../panels/panelDefinition'

/**
 * Whether a content tile has anything to put in a part. The header has the title and the panel type's header actions.
 * The footer needs something from the panel type.
 */
export function hasPart(panel: ContentPanel, part: keyof ContentPanelParts, slots: PanelSlots): boolean {
    switch (part) {
        case 'header':
            return !!panel.title || slots.header
        case 'footer':
            return slots.footer
    }
}

export function showsPart(panel: ContentPanel, part: keyof ContentPanelParts): boolean {
    return panel.parts?.[part] !== false
}

export function isPartShown(panel: ContentPanel, part: keyof ContentPanelParts, slots: PanelSlots): boolean {
    return hasPart(panel, part, slots) && showsPart(panel, part)
}
