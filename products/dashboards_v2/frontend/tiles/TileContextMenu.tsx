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
import { tilePartsAction } from '../presentation/tileParts'
import { widgetSlots } from '../widgets/widgetDefinition'
import { findWidget } from '../widgets/widgetSpec'
import { applyTileActionFilters } from './applyTileActions'
import type { TileAction } from './tileAction'

function isUsable(action: TileAction): boolean {
    if (action.disabledReason) {
        return false
    }
    return action.submenu ? action.submenu.some(isUsable) : true
}

/** Whether `TileContextMenu` opens a menu for these actions. */
export function hasTileMenu(actions: TileAction[]): boolean {
    return actions.some(isUsable)
}

export function useContentTileActions(id: string, widget: ContentWidget): TileAction[] {
    const { dashboard, activeTab, widgets, disabledReasonFor, onEdit, tileActions } = useDashboardV2()
    const otherTabs = gridTabs(dashboard).filter((tab) => tab.id !== activeTab.id)
    const definition = findWidget(widgets, widget.type)

    const actions: TileAction[] = []
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

export function useSectionActions(id: string, widget: SectionWidget, onStartRename: () => void): TileAction[] {
    const { disabledReasonFor, onEdit, tileActions } = useDashboardV2()
    const actions: TileAction[] = [
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

function TileMenuEntry({ action }: { action: TileAction }): JSX.Element {
    if (action.submenu && action.choice) {
        const selected = action.submenu.find((child) => child.checked)?.key ?? null
        return (
            <ContextMenuSub>
                <ContextMenuSubTrigger data-attr={action.dataAttr} disabled={!!action.disabledReason}>
                    {action.label}
                </ContextMenuSubTrigger>
                <ContextMenuSubContent>
                    <ContextMenuRadioGroup
                        value={selected}
                        onValueChange={(value) => action.submenu?.find((child) => child.key === value)?.onSelect?.()}
                    >
                        {action.submenu.map((child) => (
                            <ContextMenuRadioItem
                                key={child.key}
                                value={child.key}
                                data-attr={child.dataAttr}
                                disabled={!!child.disabledReason}
                            >
                                {child.label}
                            </ContextMenuRadioItem>
                        ))}
                    </ContextMenuRadioGroup>
                </ContextMenuSubContent>
            </ContextMenuSub>
        )
    }
    if (action.submenu) {
        return (
            <ContextMenuSub>
                <ContextMenuSubTrigger data-attr={action.dataAttr} disabled={!!action.disabledReason}>
                    {action.label}
                </ContextMenuSubTrigger>
                <ContextMenuSubContent>
                    {action.submenu.map((child) => (
                        <TileMenuEntry key={child.key} action={child} />
                    ))}
                </ContextMenuSubContent>
            </ContextMenuSub>
        )
    }
    if (action.checked !== undefined) {
        return (
            <ContextMenuCheckboxItem
                data-attr={action.dataAttr}
                checked={action.checked}
                disabled={!!action.disabledReason}
                title={action.disabledReason ?? undefined}
                onCheckedChange={() => action.onSelect?.()}
            >
                {action.label}
            </ContextMenuCheckboxItem>
        )
    }
    return (
        <ContextMenuItem
            data-attr={action.dataAttr}
            variant={action.destructive ? 'destructive' : 'default'}
            disabled={!!action.disabledReason}
            onClick={action.onSelect}
        >
            {action.label}
        </ContextMenuItem>
    )
}

/** Actions first, then how the tile looks, then destructive actions on their own. Empty groups are left out. */
function menuGroups(actions: TileAction[]): { key: string; label?: string; actions: TileAction[] }[] {
    const groups = [
        { key: 'actions', label: 'Actions', actions: actions.filter((action) => !action.group && !action.destructive) },
        { key: 'display', label: 'Display', actions: actions.filter((action) => action.group === 'display') },
        { key: 'destructive', actions: actions.filter((action) => action.destructive) },
    ]
    return groups.filter((group) => group.actions.length > 0)
}

/**
 * Opens the tile's actions on right-click. When the person may use none of them, it renders the children alone so the
 * browser's own menu still shows.
 */
export function TileContextMenu({ actions, children }: { actions: TileAction[]; children: ReactNode }): JSX.Element {
    if (!hasTileMenu(actions)) {
        return <>{children}</>
    }
    return (
        <ContextMenu>
            <ContextMenuTrigger
                render={
                    // A tile inside a section has its own menu, so its right-click must not also open the section's.
                    <div
                        className="DashboardV2__menu-trigger contents"
                        onContextMenu={(event) => event.stopPropagation()}
                    />
                }
            >
                {children}
            </ContextMenuTrigger>
            {/* Returning focus to the trigger would blur a rename input the menu just opened. */}
            <ContextMenuContent finalFocus={false}>
                {menuGroups(actions).map((group, index) => (
                    <ContextMenuGroup key={group.key}>
                        {index > 0 && <ContextMenuSeparator />}
                        {group.label && <ContextMenuLabel>{group.label}</ContextMenuLabel>}
                        {group.actions.map((action) => (
                            <TileMenuEntry key={action.key} action={action} />
                        ))}
                    </ContextMenuGroup>
                ))}
            </ContextMenuContent>
        </ContextMenu>
    )
}
