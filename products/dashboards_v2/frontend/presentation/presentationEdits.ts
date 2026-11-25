import {
    type ContentWidgetParts,
    type Dashboard,
    type Tile,
    type TileAppearance,
    isSection,
    isSectionWidget,
} from '../dashboard/dashboardTypes'
import { changeTileEverywhere, changeTilesWhere } from '../dashboard/tileTree'

/**
 * Presentational edits: they change how a tile looks, such as which of its parts show, and never where a tile sits or
 * what it contains. Layout edits live in `dashboardEdits.ts`. `applyEdit` sends these here and settles the layout after.
 */
export type PresentationEdit =
    | { edit: 'setTileParts'; id: string; parts: ContentWidgetParts }
    | { edit: 'setTileAppearance'; id: string; appearance: TileAppearance }
    | { edit: 'setTilesSetting'; ids: string[]; setting: TileSetting; shown: boolean }

export type TileSetting = keyof ContentWidgetParts | keyof TileAppearance

function withSetting({ widget, ...tile }: Tile, setting: TileSetting, shown: boolean): Tile {
    if (setting === 'border') {
        return { ...tile, widget: { ...widget, appearance: { ...widget.appearance, border: shown } } }
    }
    if (isSectionWidget(widget)) {
        return { ...tile, widget }
    }
    if (setting === 'background') {
        return { ...tile, widget: { ...widget, appearance: { ...widget.appearance, background: shown } } }
    }
    return { ...tile, widget: { ...widget, parts: { ...widget.parts, [setting]: shown } } }
}

export function applyPresentationEdit(dashboard: Dashboard, edit: PresentationEdit): Dashboard {
    switch (edit.edit) {
        case 'setTileParts':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? tile : { ...tile, widget: { ...tile.widget, parts: edit.parts } }
            )
        case 'setTileAppearance':
            return changeTileEverywhere(dashboard, edit.id, ({ widget, ...tile }) => ({
                ...tile,
                widget: { ...widget, appearance: edit.appearance },
            }))
        case 'setTilesSetting':
            return changeTilesWhere(
                dashboard,
                (tile) => edit.ids.includes(tile.id),
                (tile) => withSetting(tile, edit.setting, edit.shown)
            )
    }
}
