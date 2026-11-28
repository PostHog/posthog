import type { CSSProperties } from 'react'

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

/** A saved color can be any CSS color, so no class can carry it. */
export function tileBackgroundStyle(color: string | null | undefined): CSSProperties | undefined {
    if (!color) {
        return undefined
    }
    if (color === NO_BACKGROUND) {
        return { backgroundColor: NO_BACKGROUND }
    }
    // Mixed into the card's own background, so a theme color reads in light and dark mode.
    return { backgroundColor: `color-mix(in oklab, ${color} 8%, var(--card))` }
}
