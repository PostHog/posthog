import { type ContentPanelParts, type TileAppearance } from '../../panels/core/panelSchema'
import { type Dashboard, type Tile, isSectionPanel } from '../document/dashboardTypes'
import { changeTilesWhere } from '../document/tileTree'

/**
 * Presentational edits: they change how a tile looks, such as which of its parts show, and never where a tile sits or
 * what it contains. Layout edits live in `dashboardEdits.ts`. `applyEdit` sends these here and settles the layout after.
 */
export type PresentationEdit =
    | { edit: 'setTilesParts'; ids: string[]; parts: ContentPanelParts }
    | { edit: 'setTilesAppearance'; ids: string[]; appearance: AppearanceChange }

/** A null removes the setting, so the tile goes back to its default. */
export type AppearanceChange = { [Key in keyof TileAppearance]?: TileAppearance[Key] | null }

function withAppearance(current: TileAppearance | undefined, change: AppearanceChange): TileAppearance {
    const next: Record<string, unknown> = { ...current }
    for (const [key, value] of Object.entries(change)) {
        if (value === null) {
            delete next[key]
        } else if (value !== undefined) {
            next[key] = value
        }
    }
    return next
}

function changeParts({ panel, ...tile }: Tile, parts: ContentPanelParts): Tile {
    if (isSectionPanel(panel)) {
        return { ...tile, panel }
    }
    return { ...tile, panel: { ...panel, parts: { ...panel.parts, ...parts } } }
}

function changeAppearance({ panel, ...tile }: Tile, change: AppearanceChange): Tile {
    if (!isSectionPanel(panel)) {
        return { ...tile, panel: { ...panel, appearance: withAppearance(panel.appearance, change) } }
    }
    if (change.border === undefined) {
        return { ...tile, panel }
    }
    return { ...tile, panel: { ...panel, appearance: withAppearance(panel.appearance, { border: change.border }) } }
}

export function applyPresentationEdit(dashboard: Dashboard, edit: PresentationEdit): Dashboard {
    const picked = (tile: Tile): boolean => edit.ids.includes(tile.id)
    switch (edit.edit) {
        case 'setTilesParts':
            return changeTilesWhere(dashboard, picked, (tile) => changeParts(tile, edit.parts))
        case 'setTilesAppearance':
            return changeTilesWhere(dashboard, picked, (tile) => changeAppearance(tile, edit.appearance))
    }
}
