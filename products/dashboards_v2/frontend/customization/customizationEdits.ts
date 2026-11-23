import { type Dashboard, isSection } from '../layout/dashboardTypes'
import { changeTileEverywhere } from '../layout/tileTree'
import type { ContentWidgetParts } from './tileParts'
import type { DashboardAppearance } from './tileSpacing'

/** Edits to how a dashboard looks rather than where its tiles sit. `applyEdit` settles the layout after each one. */
export type CustomizationEdit =
    | { edit: 'setTileParts'; id: string; parts: ContentWidgetParts }
    | { edit: 'setAppearance'; patch: DashboardAppearance }

export function applyCustomizationEdit(dashboard: Dashboard, edit: CustomizationEdit): Dashboard {
    switch (edit.edit) {
        case 'setTileParts':
            return changeTileEverywhere(dashboard, edit.id, (tile) =>
                isSection(tile) ? tile : { ...tile, widget: { ...tile.widget, parts: edit.parts } }
            )
        case 'setAppearance':
            return { ...dashboard, appearance: { ...dashboard.appearance, ...edit.patch } }
    }
}
