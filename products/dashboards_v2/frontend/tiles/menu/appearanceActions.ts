import { type Tile, isSectionPanel } from '../../dashboard/document/dashboardTypes'
import type { PresentationEdit } from '../../dashboard/edits/presentationEdits'
import type { MenuAction } from '../../menu/menuAction'
import { type PanelType, panelSlots } from '../../panels/core/panelDefinition'
import { findPanel } from '../../panels/core/panelSpec'
import { NO_BACKGROUND, showsBorder } from '../core/tileAppearance'
import { hasPart, showsPart } from '../core/tileParts'

type TileSetting = 'header' | 'footer' | 'border'
type MenuHead = Pick<MenuAction, 'key' | 'label' | 'dataAttr'>

const SETTINGS: { setting: TileSetting; label: string }[] = [
    { setting: 'header', label: 'Header' },
    { setting: 'footer', label: 'Footer' },
    { setting: 'border', label: 'Border' },
]

/** The colors the menu offers. Each is a theme color, so the tint follows light and dark mode. */
const BACKGROUND_COLOR_PRESETS: { key: string; label: string; color: string }[] = [
    { key: 'blue', label: 'Blue', color: 'var(--color-blue-500)' },
    { key: 'green', label: 'Green', color: 'var(--color-green-500)' },
    { key: 'yellow', label: 'Yellow', color: 'var(--color-yellow-500)' },
    { key: 'red', label: 'Red', color: 'var(--color-red-500)' },
    { key: 'purple', label: 'Purple', color: 'var(--color-purple-500)' },
]

/** Null when the setting does not apply to the tile. */
function settingOn({ panel }: Pick<Tile, 'panel'>, setting: TileSetting, panels: PanelType[]): boolean | null {
    if (setting === 'border') {
        return showsBorder(panel)
    }
    if (isSectionPanel(panel)) {
        return null
    }
    const definition = findPanel(panels, panel.type)
    return hasPart(panel, setting, panelSlots(definition)) ? showsPart(panel, setting) : null
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
    tiles: Pick<Tile, 'id' | 'panel'>[],
    panels: PanelType[],
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction | null {
    const submenu = SETTINGS.flatMap(({ setting, label }): MenuAction[] => {
        const applies = tiles.flatMap((tile) => {
            const on = settingOn(tile, setting, panels)
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
    tiles: Pick<Tile, 'id' | 'panel'>[],
    panels: PanelType[],
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction | null {
    const applies = tiles.flatMap(({ id, panel }) => {
        if (isSectionPanel(panel)) {
            return []
        }
        return findPanel(panels, panel.type)?.allowedCustomizations?.includes('backgroundColor')
            ? [{ id, color: panel.appearance?.backgroundColor ?? null }]
            : []
    })
    if (applies.length === 0) {
        return null
    }
    const ids = applies.map(({ id }) => id)
    const current = applies.every(({ color }) => color === applies[0].color) ? applies[0].color : undefined
    const choices: { key: string; label: string; color: string | null }[] = [
        { key: 'default', label: 'Default', color: null },
        { key: 'none', label: 'None', color: NO_BACKGROUND },
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
