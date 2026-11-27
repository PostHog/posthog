import posthog from 'posthog-js'

import { IconPlus } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { useDashboard } from '../../dashboard/core/dashboardContext'
import type { DashboardEdit } from '../../dashboard/edits/dashboardEdits'

export function AddTileMenu({ gridId, label }: { gridId: string; label?: string }): JSX.Element {
    const { panels, onEdit } = useDashboard()
    const addTile = (panel: Extract<DashboardEdit, { edit: 'addTile' }>['panel']): void => {
        onEdit({ edit: 'addTile', grid: gridId, panel })
        // pinned: analytics property name, kept from when panels were called widgets.
        posthog.capture('dashboard v2 tile added', { widget_type: panel.type })
    }
    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <Button
                        size={label ? 'sm' : 'icon-xs'}
                        variant={label ? 'outline' : 'default'}
                        tooltip={label ? undefined : 'Add'}
                        aria-label="Add"
                        data-attr="dashboard-v2-add"
                    />
                }
            >
                <IconPlus />
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
                <DropdownMenuGroup>
                    <DropdownMenuLabel>Add a tile</DropdownMenuLabel>
                    {panels.flatMap(({ type, addTileOptions }) =>
                        addTileOptions.map(({ label: itemLabel, create }) => (
                            <DropdownMenuItem key={`${type}-${itemLabel}`} onClick={() => addTile(create())}>
                                {itemLabel}
                            </DropdownMenuItem>
                        ))
                    )}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => addTile({ type: 'section', title: 'Untitled section', tiles: [] })}>
                    Section
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
