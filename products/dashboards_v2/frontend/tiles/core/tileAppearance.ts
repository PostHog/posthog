import type { SectionPanel } from '../../dashboard/document/dashboardTypes'
import { type SavedPanel } from '../../panels/core/panelSchema'
import type { TileCustomization } from '../../panels/core/panelSpec'

export function showsBorder(panel: SavedPanel | SectionPanel): boolean {
    return panel.appearance?.border !== false
}

export const NO_BACKGROUND = 'transparent'

/** The color the tile's panel type lets it show, or null for the card's own background. */
export function tileBackgroundColor(panel: SavedPanel, customizations: TileCustomization[]): string | null {
    return (customizations.includes('backgroundColor') && panel.appearance?.backgroundColor) || null
}
