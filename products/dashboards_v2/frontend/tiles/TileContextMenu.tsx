import type { ReactNode } from 'react'

import {
    ContextMenu,
    ContextMenuCheckboxItem,
    ContextMenuContent,
    ContextMenuGroup,
    ContextMenuItem,
    ContextMenuLabel,
    ContextMenuRadioGroup,
    ContextMenuRadioItem,
    ContextMenuSeparator,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from '@posthog/quill'

import type { DashboardEdit } from '../dashboard/dashboardEdits'
import { downloadImageAction } from '../dashboard/dashboardImage'
import { type ContentWidget, type SectionWidget, gridTabs, widgetRef } from '../dashboard/dashboardTypes'
import { type DashboardV2State, useDashboardV2 } from '../dashboard/dashboardV2Context'
import type { MenuAction } from '../dashboard/menuAction'
import { MenuActionList, type MenuParts } from '../dashboard/MenuActionList'
import { everyTile } from '../dashboard/tileTree'
import { showAction } from '../presentation/tileAppearance'
import { findWidget } from '../widgets/widgetSpec'
import { applyTileActionFilters } from './applyTileActions'

const CONTEXT_MENU_PARTS: MenuParts = {
    Group: ContextMenuGroup,
    Label: ContextMenuLabel,
    Separator: ContextMenuSeparator,
    Item: ContextMenuItem,
    CheckboxItem: ContextMenuCheckboxItem,
    Sub: ContextMenuSub,
    SubTrigger: ContextMenuSubTrigger,
    SubContent: ContextMenuSubContent,
    RadioGroup: ContextMenuRadioGroup,
    RadioItem: ContextMenuRadioItem,
}

function isUsable(action: MenuAction): boolean {
    if (action.disabledReason) {
        return false
    }
    return action.submenu ? action.submenu.some(isUsable) : true
}

/** Whether `TileContextMenu` opens a menu for these actions. */
export function hasTileMenu(actions: MenuAction[]): boolean {
    return actions.some(isUsable)
}

export function useContentTileActions(id: string, widget: ContentWidget): MenuAction[] {
    const {
        dashboard,
        activeTab,
        widgets,
        disabledReasonFor,
        onEdit,
        tileActions,
        downloadImage,
        downloadingImage,
        presentTile,
    } = useDashboardV2()
    const otherTabs = gridTabs(dashboard).filter((tab) => tab.id !== activeTab.id)
    const definition = findWidget(widgets, widget.type)

    const actions: MenuAction[] = [
        {
            key: 'present',
            label: 'Present',
            dataAttr: 'dashboard-v2-tile-present',
            group: 'view',
            disabledReason: null,
            onSelect: () => presentTile(id),
        },
    ]
    if (otherTabs.length > 0) {
        actions.push({
            key: 'move',
            label: 'Move to tab',
            dataAttr: 'dashboard-v2-tile-move-to-tab',
            group: 'dashboard',
            disabledReason: disabledReasonFor('moveTile'),
            submenu: otherTabs.map((tab) => ({
                key: tab.id,
                label: tab.title,
                dataAttr: 'dashboard-v2-tile-move-to-tab-item',
                disabledReason: disabledReasonFor('moveTile'),
                onSelect: () => onEdit({ edit: 'moveTile', id, grid: tab.id }),
            })),
        })
        actions.push({
            key: 'add-to-tab',
            label: 'Also show on tab',
            dataAttr: 'dashboard-v2-tile-add-to-tab',
            group: 'dashboard',
            disabledReason: disabledReasonFor('addToGrid'),
            submenu: otherTabs.map((tab) => {
                // A tab already showing this widget is ticked, and picking it again takes the widget off that tab.
                const shown = widget.ref
                    ? everyTile(tab.tiles).find((tile) => widgetRef(tile) === widget.ref)
                    : undefined
                return {
                    key: tab.id,
                    label: tab.title,
                    dataAttr: 'dashboard-v2-tile-add-to-tab-item',
                    checked: !!shown,
                    disabledReason: disabledReasonFor(shown ? 'removeTile' : 'addToGrid'),
                    onSelect: () =>
                        onEdit(shown ? { edit: 'removeTile', id: shown.id } : { edit: 'addToGrid', id, grid: tab.id }),
                }
            }),
        })
    }
    actions.push(tileImageAction(id, downloadingImage, downloadImage))
    const show = showAction(TILE_SHOW, [{ id, widget }], widgets, disabledReasonFor('setTilesSetting'), onEdit)
    if (show) {
        actions.push(show)
    }
    if (definition?.menuActions) {
        actions.push(
            ...definition.menuActions({
                widget,
                setConfig: (config) => onEdit({ edit: 'setWidgetConfig', id, config }),
                disabledReason: disabledReasonFor('setWidgetConfig'),
            })
        )
    }
    actions.push({
        key: 'remove',
        label: 'Remove tile',
        dataAttr: 'dashboard-v2-tile-remove',
        disabledReason: disabledReasonFor('removeTile'),
        destructive: true,
        onSelect: () => onEdit({ edit: 'removeTile', id }),
    })
    return applyTileActionFilters(
        actions,
        { id, widget },
        definition?.tileActions && ((list) => definition.tileActions!(list, { widget })),
        tileActions
    )
}

// pinned: `dashboard-v2-tile-parts` data-attrs shipped before border and background joined this menu.
const TILE_SHOW = { key: 'parts', label: 'Show', dataAttr: 'dashboard-v2-tile-parts' }

function tileImageAction(
    id: string,
    downloadingImage: boolean,
    downloadImage: DashboardV2State['downloadImage']
): MenuAction {
    return downloadImageAction('Download as image', 'dashboard-v2-tile-download-image', downloadingImage, (format) =>
        downloadImage(format, id)
    )
}

const AUTO_LAYOUT_COLUMNS = [1, 2, 3, 4]

function autoLayoutAction(
    id: string,
    disabledReason: string | null,
    onEdit: (edit: DashboardEdit) => void
): MenuAction {
    return {
        key: 'auto-layout',
        label: 'Auto layout',
        dataAttr: 'dashboard-v2-section-auto-layout',
        disabledReason,
        group: 'display',
        submenu: AUTO_LAYOUT_COLUMNS.map((columns) => ({
            key: String(columns),
            label: columns === 1 ? '1 column' : `${columns} columns`,
            dataAttr: 'dashboard-v2-section-auto-layout-item',
            disabledReason,
            keepOpen: true,
            onSelect: () => onEdit({ edit: 'autoLayout', grid: id, columns }),
        })),
    }
}

export function useSectionActions(id: string, widget: SectionWidget, onStartRename: () => void): MenuAction[] {
    const { widgets, disabledReasonFor, onEdit, tileActions, downloadImage, downloadingImage } = useDashboardV2()
    const show = showAction(TILE_SHOW, [{ id, widget }], widgets, disabledReasonFor('setTilesSetting'), onEdit)
    const actions: MenuAction[] = [
        {
            key: 'rename',
            label: 'Rename',
            dataAttr: 'dashboard-v2-section-menu-rename',
            disabledReason: disabledReasonFor('updateSection'),
            onSelect: onStartRename,
        },
        tileImageAction(id, downloadingImage, downloadImage),
        autoLayoutAction(id, disabledReasonFor('autoLayout'), onEdit),
        ...(show ? [show] : []),
        {
            key: 'remove',
            label: 'Remove section and its tiles',
            dataAttr: 'dashboard-v2-section-remove',
            disabledReason: disabledReasonFor('removeTile'),
            destructive: true,
            onSelect: () => onEdit({ edit: 'removeTile', id }),
        },
    ]
    return applyTileActionFilters(actions, { id, widget }, undefined, tileActions)
}

/**
 * Opens the tile's actions on right-click. When the person may use none of them, it renders the children alone so the
 * browser's own menu still shows.
 */
export function TileContextMenu({ actions, children }: { actions: MenuAction[]; children: ReactNode }): JSX.Element {
    if (!hasTileMenu(actions)) {
        return <>{children}</>
    }
    return (
        <ContextMenu>
            <ContextMenuTrigger
                render={
                    // A tile inside a section has its own menu, so its right-click must not also open the section's.
                    <div
                        className="TileContextMenu__trigger contents"
                        onContextMenu={(event) => event.stopPropagation()}
                    />
                }
            >
                {children}
            </ContextMenuTrigger>
            {/* Returning focus to the trigger would blur a rename input the menu just opened. */}
            <ContextMenuContent finalFocus={false}>
                <MenuActionList actions={actions} parts={CONTEXT_MENU_PARTS} />
            </ContextMenuContent>
        </ContextMenu>
    )
}
