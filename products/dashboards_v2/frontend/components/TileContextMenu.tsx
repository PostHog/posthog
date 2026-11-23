import type { ReactNode } from 'react'

import {
    ContextMenu,
    ContextMenuCheckboxItem,
    ContextMenuContent,
    ContextMenuItem,
    ContextMenuSub,
    ContextMenuSubContent,
    ContextMenuSubTrigger,
    ContextMenuTrigger,
} from '@posthog/quill'

import { tilePartsAction } from '../customization/tilePartsAction'
import { useDashboardV2 } from '../dashboardV2Context'
import type { ContentWidget } from '../layout/dashboardTypes'

/** One thing a person can do to a tile, shared by the right-click menu and the hover toolbar so the two agree. */
export interface TileAction {
    key: string
    label: string
    dataAttr: string
    disabledReason: string | null
    destructive?: boolean
    onSelect?: () => void
    submenu?: TileAction[]
    /** Set on an action that is a toggle: whether it is on. */
    checked?: boolean
}

function isUsable(action: TileAction): boolean {
    if (action.disabledReason) {
        return false
    }
    return action.submenu ? action.submenu.some(isUsable) : true
}

export function useContentTileActions(id: string, widget: ContentWidget): TileAction[] {
    const { dashboard, activeTab, disabledReasonFor, onEdit } = useDashboardV2()
    const otherTabs = dashboard.tabs.filter((tab) => tab.id !== activeTab.id)

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
    const parts = tilePartsAction(id, widget, disabledReasonFor('setTileParts'), onEdit)
    if (parts) {
        actions.push(parts)
    }
    actions.push({
        key: 'remove',
        label: 'Remove tile',
        dataAttr: 'dashboard-v2-tile-remove',
        disabledReason: disabledReasonFor('removeTile'),
        destructive: true,
        onSelect: () => onEdit({ edit: 'removeTile', id }),
    })
    return actions
}

export function useSectionActions(id: string, collapsed: boolean, onStartRename: () => void): TileAction[] {
    const { disabledReasonFor, onEdit, onSectionFoldedChange } = useDashboardV2()
    return [
        {
            key: 'rename',
            label: 'Rename',
            dataAttr: 'dashboard-v2-section-menu-rename',
            disabledReason: disabledReasonFor('updateSection'),
            onSelect: onStartRename,
        },
        {
            key: 'toggle',
            label: collapsed ? 'Expand' : 'Collapse',
            dataAttr: 'dashboard-v2-section-menu-toggle',
            disabledReason: null,
            onSelect: () => onSectionFoldedChange(id, !collapsed),
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
}

function TileMenuEntry({ action }: { action: TileAction }): JSX.Element {
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

/**
 * Opens the tile's actions on right-click. When the person may use none of them, it renders the children alone so the
 * browser's own menu still shows.
 */
export function TileContextMenu({ actions, children }: { actions: TileAction[]; children: ReactNode }): JSX.Element {
    if (!actions.some(isUsable)) {
        return <>{children}</>
    }
    return (
        <ContextMenu>
            <ContextMenuTrigger render={<div className="DashboardV2__menu-trigger contents" />}>
                {children}
            </ContextMenuTrigger>
            {/* Returning focus to the trigger would blur a rename input the menu just opened. */}
            <ContextMenuContent finalFocus={false}>
                {actions.map((action) => (
                    <TileMenuEntry key={action.key} action={action} />
                ))}
            </ContextMenuContent>
        </ContextMenu>
    )
}
