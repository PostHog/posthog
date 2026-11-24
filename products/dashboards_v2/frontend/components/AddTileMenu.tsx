import { useActions } from 'kea'

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

import { dashboardV2Logic } from '../dashboardV2Logic'
import { NEW_TILES } from '../widgets/newTiles'

export function AddTileMenu({ gridId, label }: { gridId: string; label?: string }): JSX.Element {
    const { applyDashboardEdit } = useActions(dashboardV2Logic)
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
                    {NEW_TILES.map(({ label: tileLabel, widget }) => (
                        <DropdownMenuItem
                            key={tileLabel}
                            onClick={() => applyDashboardEdit({ edit: 'addTile', grid: gridId, widget })}
                        >
                            {tileLabel}
                        </DropdownMenuItem>
                    ))}
                </DropdownMenuGroup>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                    onClick={() =>
                        applyDashboardEdit({
                            edit: 'addTile',
                            grid: gridId,
                            widget: { type: 'section', title: 'Untitled section', tiles: [] },
                        })
                    }
                >
                    Section
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
