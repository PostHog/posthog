import { type ContentWidget, type SectionWidget, type Tile, isSectionWidget } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import { type WidgetDefinition, widgetSlots } from '../widgets/widgetDefinition'
import { type WidgetAppearanceOptions, findWidget } from '../widgets/widgetSpec'
import type { PresentationEdit, TileSetting } from './presentationEdits'
import { hasPart, showsPart } from './tileParts'

export function showsBackground(widget: ContentWidget, options: WidgetAppearanceOptions): boolean {
    return !options.background || widget.appearance?.background !== false
}

export function showsBorder(widget: ContentWidget | SectionWidget): boolean {
    return widget.appearance?.border !== false
}

const SETTINGS: { setting: TileSetting; label: string }[] = [
    { setting: 'header', label: 'Header' },
    { setting: 'footer', label: 'Footer' },
    { setting: 'background', label: 'Background' },
    { setting: 'border', label: 'Border' },
]

/** Null when the setting does not apply to the tile. */
function settingOn(
    { widget }: Pick<Tile, 'widget'>,
    setting: TileSetting,
    widgets: WidgetDefinition[]
): boolean | null {
    if (setting === 'border') {
        return showsBorder(widget)
    }
    if (isSectionWidget(widget)) {
        return null
    }
    const definition = findWidget(widgets, widget.type)
    if (setting === 'background') {
        return definition?.appearance?.background ? showsBackground(widget, definition.appearance) : null
    }
    return hasPart(widget, setting, widgetSlots(definition)) ? showsPart(widget, setting) : null
}

/** Each setting is ticked while it is on for every tile it applies to. */
export function showAction(
    menu: { key: string; label: string; dataAttr: string },
    tiles: Pick<Tile, 'id' | 'widget'>[],
    widgets: WidgetDefinition[],
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction | null {
    const submenu = SETTINGS.flatMap(({ setting, label }): MenuAction[] => {
        const applies = tiles.flatMap((tile) => {
            const on = settingOn(tile, setting, widgets)
            return on === null ? [] : [{ id: tile.id, on }]
        })
        if (applies.length === 0) {
            return []
        }
        const allOn = applies.every(({ on }) => on)
        return [
            {
                key: setting,
                label,
                dataAttr: `${menu.dataAttr}-${setting}`,
                disabledReason,
                checked: allOn,
                onSelect: () =>
                    onEdit({ edit: 'setTilesSetting', ids: applies.map(({ id }) => id), setting, shown: !allOn }),
            },
        ]
    })
    if (submenu.length === 0) {
        return null
    }
    return { ...menu, group: 'display', disabledReason, submenu }
}
