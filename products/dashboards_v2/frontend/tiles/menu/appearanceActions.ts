import { type Tile, isSectionPanel } from '../../dashboard/document/dashboardTypes'
import type { PresentationEdit } from '../../dashboard/edits/presentationEdits'
import type { MenuAction } from '../../menu/menuAction'
import { type PanelType, panelSlots } from '../../panels/core/panelDefinition'
import { type TileDescriptionMode, shownDescription } from '../../panels/core/panelSchema'
import { findPanel } from '../../panels/core/panelSpec'
import { TILE_BACKGROUND_COLORS } from '../../panels/core/tileBackground'
import { NO_BACKGROUND, showsBorder } from '../core/tileAppearance'
import { hasPart, showsPart } from '../core/tileParts'

type TileSetting = 'header' | 'footer' | 'border'
type MenuHead = Pick<MenuAction, 'key' | 'label' | 'dataAttr'>

const SETTINGS: { setting: TileSetting; label: string }[] = [
    { setting: 'header', label: 'Header' },
    { setting: 'footer', label: 'Footer' },
    { setting: 'border', label: 'Border' },
]

const BACKGROUND_COLOR_PRESETS: { key: string; label: string; color: string }[] = [
    { key: 'blue', label: 'Blue', color: TILE_BACKGROUND_COLORS.blue },
    { key: 'green', label: 'Green', color: TILE_BACKGROUND_COLORS.green },
    { key: 'yellow', label: 'Yellow', color: TILE_BACKGROUND_COLORS.yellow },
    { key: 'red', label: 'Red', color: TILE_BACKGROUND_COLORS.red },
    { key: 'purple', label: 'Purple', color: TILE_BACKGROUND_COLORS.purple },
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

/** Each setting is ticked while it is on for every tile it applies to. A tile's description choices follow under their own heading. */
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
    const entries = [...submenu, ...descriptionChoices(menu, tiles, disabledReason, onEdit)]
    if (entries.length === 0) {
        return null
    }
    return { ...menu, group: 'display', disabledReason, submenu: entries }
}

export function backgroundColorAction(
    menu: MenuHead,
    tiles: Pick<Tile, 'id' | 'panel'>[],
    panels: PanelType[],
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction | null {
    const applies = tiles.flatMap(({ id, panel }) => {
        const allowed =
            isSectionPanel(panel) || findPanel(panels, panel.type)?.allowedCustomizations?.includes('backgroundColor')
        return allowed ? [{ id, color: panel.appearance?.backgroundColor ?? null }] : []
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

const DESCRIPTION_MODES: { mode: TileDescriptionMode; label: string }[] = [
    { mode: 'icon', label: 'In an icon' },
    { mode: 'below', label: 'Below the title' },
    { mode: 'hidden', label: 'Hidden' },
]

/** One exclusive group in the Show submenu, for the tiles and sections that have a description. */
function descriptionChoices(
    menu: MenuHead,
    tiles: Pick<Tile, 'id' | 'panel'>[],
    disabledReason: string | null,
    onEdit: (edit: PresentationEdit) => void
): MenuAction[] {
    // The description sits in the header, so a tile whose header is off has nothing to choose. A section always shows
    // its header.
    const applies = tiles.flatMap(({ id, panel }) => {
        if (!panel.description || !(isSectionPanel(panel) || showsPart(panel, 'header'))) {
            return []
        }
        return [{ id, mode: shownDescription(panel).mode }]
    })
    if (applies.length === 0) {
        return []
    }
    const ids = applies.map(({ id }) => id)
    return DESCRIPTION_MODES.map(({ mode, label }) => ({
        key: `description-${mode}`,
        label,
        section: 'Description',
        exclusive: true,
        dataAttr: `${menu.dataAttr}-description`,
        disabledReason,
        checked: applies.every((tile) => tile.mode === mode),
        onSelect: () =>
            onEdit({ edit: 'setTilesAppearance', ids, appearance: { description: mode === 'icon' ? null : mode } }),
    }))
}
