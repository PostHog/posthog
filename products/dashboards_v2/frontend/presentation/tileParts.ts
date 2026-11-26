import type { SavedPanel, ContentPanelParts } from '../dashboard/document/dashboardTypes'
import type { PanelSlots } from '../panels/core/panelDefinition'

/**
 * Whether a content tile has anything to put in a part. The header has the title and the panel type's header actions.
 * The footer needs something from the panel type.
 */
export function hasPart(panel: SavedPanel, part: keyof ContentPanelParts, slots: PanelSlots): boolean {
    switch (part) {
        case 'header':
            return !!panel.title || slots.hasHeader
        case 'footer':
            return slots.hasFooter
    }
}

export function showsPart(panel: SavedPanel, part: keyof ContentPanelParts): boolean {
    return panel.parts?.[part] !== false
}

export function isPartShown(panel: SavedPanel, part: keyof ContentPanelParts, slots: PanelSlots): boolean {
    return hasPart(panel, part, slots) && showsPart(panel, part)
}
