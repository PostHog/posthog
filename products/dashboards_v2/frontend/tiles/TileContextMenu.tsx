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

import { type ContentWidget, type SectionWidget, gridTabs } from '../dashboard/dashboardTypes'
import { useDashboardV2 } from '../dashboard/dashboardV2Context'
import type { MenuAction } from '../dashboard/menuAction'
import { MenuActionList, type MenuParts } from '../dashboard/MenuActionList'
import { tileAppearanceAction } from '../presentation/tileAppearance'
import { tilePartsAction } from '../presentation/tileParts'
import { widgetSlots } from '../widgets/widgetDefinition'
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
    const { dashboard, activeTab, widgets, disabledReasonFor, onEdit, tileActions } = useDashboardV2()
    const otherTabs = gridTabs(dashboard).filter((tab) => tab.id !== activeTab.id)
    const definition = findWidget(widgets, widget.type)

    const actions: MenuAction[] = []
    if (otherTabs.length > 0) {
        actions.push({
            key: 'move',
            label: 'Move to tab',
            dataAttr: 'dashboard-v2-tile-move-to-tab',
            disabledReason: disabledReasonFor('moveTile'),
            submenu: otherTabs.map((tab) => ({
                key: tab.id,
                label: tab.title,
                dataAttr: 'dashboard-v2-tile-move-to-tab-item',
                disabledReason: disabledReasonFor('moveTile'),
                onSelect: () => onEdit({ edit: 'moveTile', id, grid: tab.id }),
            })),
        })
    }
    const parts = tilePartsAction(id, widget, widgetSlots(definition), disabledReasonFor('setTileParts'), onEdit)
    if (parts) {
        actions.push(parts)
    }
    const appearance = tileAppearanceAction(
        id,
        widget,
        definition?.appearance ?? {},
        disabledReasonFor('setTileAppearance'),
        onEdit
    )
    if (appearance) {
        actions.push(appearance)
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

export function useSectionActions(id: string, widget: SectionWidget, onStartRename: () => void): MenuAction[] {
    const { disabledReasonFor, onEdit, tileActions } = useDashboardV2()
    const actions: MenuAction[] = [
        {
            key: 'rename',
            label: 'Rename',
            dataAttr: 'dashboard-v2-section-menu-rename',
            disabledReason: disabledReasonFor('updateSection'),
            onSelect: onStartRename,
        },
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
