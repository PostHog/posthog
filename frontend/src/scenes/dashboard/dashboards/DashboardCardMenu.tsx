import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconEllipsis, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { urls } from 'scenes/urls'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

// Per-card actions for the grid/finder arms.
export function DashboardCardMenu({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { cutDashboard, copyDashboard, startRenaming, deleteDashboardWithConfirm } =
        useActions(dashboardsFileSystemLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger render={<Button variant="default" size="icon-sm" aria-label="Dashboard actions" />}>
                <IconEllipsis className="text-tertiary" />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="bottom">
                <DropdownMenuGroup>
                    <DropdownMenuItem onClick={() => router.actions.push(urls.dashboard(dashboardId))}>
                        Open
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => startRenaming(dashboardId)}>Rename</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => cutDashboard(dashboardId)}>Cut</DropdownMenuItem>
                    <DropdownMenuItem onClick={() => copyDashboard(dashboardId)}>
                        <IconCopy />
                        Copy
                    </DropdownMenuItem>
                    <DropdownMenuItem variant="destructive" onClick={() => deleteDashboardWithConfirm(dashboardId)}>
                        <IconTrash />
                        Delete
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
