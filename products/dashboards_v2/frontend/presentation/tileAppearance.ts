import { type ContentWidget, type SectionWidget, type Tile, isSectionWidget } from '../dashboard/dashboardTypes'
import type { MenuAction } from '../dashboard/menuAction'
import { type WidgetDefinition, widgetSlots } from '../widgets/widgetDefinition'
import { type WidgetAppearanceOptions, findWidget } from '../widgets/widgetSpec'
import type { PresentationEdit } from './presentationEdits'
import { hasPart, showsPart } from './tileParts'

export function showsBackground(widget: ContentWidget, options: WidgetAppearanceOptions): boolean {
    return !options.background || widget.appearance?.background !== false
}

export function showsBorder(widget: ContentWidget | SectionWidget): boolean {
    return widget.appearance?.border !== false
}

export function tileBackgroundColor(widget: ContentWidget, options: WidgetAppearanceOptions): string | null {
    return (options.backgroundColor && widget.appearance?.backgroundColor) || null
}

type TileSetting = 'header' | 'footer' | 'background' | 'border'
type MenuHead = Pick<MenuAction, 'key' | 'label' | 'dataAttr'>

const SETTINGS: { setting: TileSetting; label: string }[] = [
    { setting: 'header', label: 'Header' },
    { setting: 'footer', label: 'Footer' },
    { setting: 'background', label: 'Background' },
    { setting: 'border', label: 'Border' },
]

/** The colors the menu offers. Each is a theme color, so the tint follows light and dark mode. */
export const BACKGROUND_COLOR_PRESETS: { key: string; label: string; color: string }[] = [
    { key: 'blue', label: 'Blue', color: 'var(--color-blue-500)' },
    { key: 'green', label: 'Green', color: 'var(--color-green-500)' },
    { key: 'yellow', label: 'Yellow', color: 'var(--color-yellow-500)' },
    { key: 'red', label: 'Red', color: 'var(--color-red-500)' },
    { key: 'purple', label: 'Purple', color: 'var(--color-purple-500)' },
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

function settingEdit(ids: string[], setting: TileSetting, shown: boolean): PresentationEdit {
    if (setting === 'header' || setting === 'footer') {
        return { edit: 'setTilesParts', ids, parts: { [setting]: shown } }
    }
    return { edit: 'setTilesAppearance', ids, appearance: { [setting]: shown } }
}

/** Each setting is ticked while it is on for every tile it applies to. */
export function showAction(
    menu: MenuHead,
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
                    onEdit(
                        settingEdit(
                            applies.map(({ id }) => id),
                            setting,
                            !allOn
                        )
                    ),
            },
        ]
    })
    if (submenu.length === 0) {
        return null
    }
    return { ...menu, group: 'display', disabledReason, submenu }
}

export function backgroundColorAction(
    menu: MenuHead,
    tiles: Pick<Tile, 'id' | 'widget'>[],
    widgets: WidgetDefinition[],
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction | null {
    const applies = tiles.flatMap(({ id, widget }) => {
        if (isSectionWidget(widget)) {
            return []
        }
        return findWidget(widgets, widget.type)?.appearance?.backgroundColor
            ? [{ id, color: widget.appearance?.backgroundColor ?? null }]
            : []
    })
    if (applies.length === 0) {
        return null
    }
    const ids = applies.map(({ id }) => id)
    const current = applies.every(({ color }) => color === applies[0].color) ? applies[0].color : undefined
    const choices: { key: string; label: string; color: string | null }[] = [
        { key: 'none', label: 'None', color: null },
        ...BACKGROUND_COLOR_PRESETS,
    ]
    return {
        ...menu,
        group: 'display',
        disabledReason,
        choice: true,
        submenu: choices.map(({ key, color, label }) => ({
            key,
            label,
            dataAttr: `${menu.dataAttr}-item`,
            disabledReason,
            checked: current === color,
            keepOpen: true,
            onSelect: () => onEdit({ edit: 'setTilesAppearance', ids, appearance: { backgroundColor: color } }),
        })),
    }
}
