import {
    type ContentWidgetAppearance,
    type ContentWidgetParts,
    type Dashboard,
    type SectionWidgetAppearance,
    isSection,
    isSectionWidget,
} from '../dashboard/dashboardTypes'
import { changeTileEverywhere } from '../dashboard/tileTree'

/**
 * Presentational edits: they change how a tile looks, such as which of its parts show, and never where a tile sits or
 * what it contains. Layout edits live in `dashboardEdits.ts`. `applyEdit` sends these here and settles the layout after.
 */
export type PresentationEdit =
    | { edit: 'setTileParts'; id: string; parts: ContentWidgetParts }
    | { edit: 'setTileAppearance'; id: string; appearance: ContentWidgetAppearance }
    | { edit: 'setSectionAppearance'; id: string; appearance: SectionWidgetAppearance }

export function applyPresentationEdit(dashboard: Dashboard, edit: PresentationEdit): Dashboard {
    switch (edit.edit) {
        case 'setTileParts':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? tile : { ...tile, widget: { ...tile.widget, parts: edit.parts } }
            )
        case 'setTileAppearance':
            return changeTileEverywhere(dashboard, edit.id, ({ widget, ...tile }) =>
                isSectionWidget(widget)
                    ? { ...tile, widget }
                    : { ...tile, widget: { ...widget, appearance: edit.appearance } }
            )
        case 'setSectionAppearance':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? { ...tile, widget: { ...tile.widget, appearance: edit.appearance } } : tile
            )
    }
}
