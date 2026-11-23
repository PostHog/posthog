import { useActions, useValues } from 'kea'
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

import { dashboardV2Logic } from '../dashboardV2Logic'
import { type ContentWidget, type ContentWidgetParts, showsPart } from '../layout/dashboardTypes'

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

const TILE_PARTS: { key: keyof ContentWidgetParts; label: string }[] = [
    { key: 'header', label: 'Header' },
    { key: 'description', label: 'Description' },
    { key: 'footer', label: 'Footer' },
]

const HAS_PART: Record<keyof ContentWidgetParts, (widget: ContentWidget) => boolean> = {
    header: (widget) => !!widget.title,
    description: (widget) => !!widget.description,
    footer: (widget) => !!widget.footer?.length,
}

export function useContentTileActions(id: string, widget: ContentWidget): TileAction[] {
    const { dashboard, activeTab, disabledReasonFor } = useValues(dashboardV2Logic)
    const { applyDashboardEdit } = useActions(dashboardV2Logic)
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
                onSelect: () => applyDashboardEdit({ edit: 'moveTile', id, grid: tab.id }),
            })),
        })
    }
    const partsDisabledReason = disabledReasonFor('setTileParts')
    const parts = TILE_PARTS.filter(({ key }) => HAS_PART[key](widget))
    if (parts.length > 0) {
        actions.push({
            key: 'parts',
            label: 'Show',
            dataAttr: 'dashboard-v2-tile-parts',
            disabledReason: partsDisabledReason,
            submenu: parts.map(({ key, label }) => {
                const shown = showsPart(widget, key)
                const needsHeader = key === 'description' && !showsPart(widget, 'header')
                return {
                    key,
                    label,
                    dataAttr: `dashboard-v2-tile-parts-${key}`,
                    // The description lives in the header, so it cannot be turned on while the header is off.
                    disabledReason: partsDisabledReason ?? (needsHeader ? 'Show the header first' : null),
                    checked: shown,
                    onSelect: () =>
                        applyDashboardEdit({ edit: 'setTileParts', id, parts: { ...widget.parts, [key]: !shown } }),
                }
            }),
        })
    }
    actions.push({
        key: 'remove',
        label: 'Remove tile',
        dataAttr: 'dashboard-v2-tile-remove',
        disabledReason: disabledReasonFor('removeTile'),
        destructive: true,
        onSelect: () => applyDashboardEdit({ edit: 'removeTile', id }),
    })
    return actions
}

export function useSectionActions(id: string, collapsed: boolean, onStartRename: () => void): TileAction[] {
    const { disabledReasonFor } = useValues(dashboardV2Logic)
    const { applyDashboardEdit } = useActions(dashboardV2Logic)
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
            disabledReason: disabledReasonFor('updateSection'),
            onSelect: () => applyDashboardEdit({ edit: 'updateSection', id, patch: { collapsed: !collapsed } }),
        },
        {
            key: 'remove',
            label: 'Remove section and its tiles',
            dataAttr: 'dashboard-v2-section-remove',
            disabledReason: disabledReasonFor('removeTile'),
            destructive: true,
            onSelect: () => applyDashboardEdit({ edit: 'removeTile', id }),
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
