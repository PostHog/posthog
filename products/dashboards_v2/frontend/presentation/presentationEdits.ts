import { type ContentWidgetParts, type Dashboard, isSection } from '../dashboard/dashboardTypes'
import { changeTileEverywhere } from '../dashboard/tileTree'

/**
 * Presentational edits: they change how a tile looks, such as which of its parts show, and never where a tile sits or
 * what it contains. Layout edits live in `dashboardEdits.ts`. `applyEdit` sends these here and settles the layout after.
 */
export type PresentationEdit = { edit: 'setTileParts'; id: string; parts: ContentWidgetParts }

export function applyPresentationEdit(dashboard: Dashboard, edit: PresentationEdit): Dashboard {
    switch (edit.edit) {
        case 'setTileParts':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? tile : { ...tile, widget: { ...tile.widget, parts: edit.parts } }
            )
    }
}
