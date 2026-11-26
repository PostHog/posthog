import {
    type ContentWidgetParts,
    type Dashboard,
    type Tile,
    type TileAppearance,
    isSectionWidget,
} from '../dashboard/dashboardTypes'
import { changeTilesWhere } from '../dashboard/tileTree'

/**
 * Presentational edits: they change how a tile looks, such as which of its parts show, and never where a tile sits or
 * what it contains. Layout edits live in `dashboardEdits.ts`. `applyEdit` sends these here and settles the layout after.
 */
export type PresentationEdit =
    | { edit: 'setTilesParts'; ids: string[]; parts: ContentWidgetParts }
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

function changeParts({ widget, ...tile }: Tile, parts: ContentWidgetParts): Tile {
    if (isSectionWidget(widget)) {
        return { ...tile, widget }
    }
    return { ...tile, widget: { ...widget, parts: { ...widget.parts, ...parts } } }
}

function changeAppearance({ widget, ...tile }: Tile, change: AppearanceChange): Tile {
    if (!isSectionWidget(widget)) {
        return { ...tile, widget: { ...widget, appearance: withAppearance(widget.appearance, change) } }
    }
    if (change.border === undefined) {
        return { ...tile, widget }
    }
    return { ...tile, widget: { ...widget, appearance: withAppearance(widget.appearance, { border: change.border }) } }
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
