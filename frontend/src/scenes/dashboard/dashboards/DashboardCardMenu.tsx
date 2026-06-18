import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconEllipsis, IconFolder, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { moveToLogic } from 'lib/components/FileSystem/MoveTo/moveToLogic'
import { urls } from 'scenes/urls'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

// Per-card actions for the explorer/tree arms.
export function DashboardCardMenu({ dashboardId }: { dashboardId: number }): JSX.Element {
    const { cutDashboard, copyDashboard, startRenaming, deleteDashboardWithConfirm } =
        useActions(dashboardsFileSystemLogic)
    const { entryByRef } = useValues(dashboardsFileSystemLogic)
    const { openMoveToModal } = useActions(moveToLogic)
    // The dashboard's FileSystem row, which the canonical searchable move-to-folder modal moves.
    const entry = entryByRef[String(dashboardId)]

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
                    {entry ? (
                        <DropdownMenuItem onClick={() => openMoveToModal([entry])}>
                            <IconFolder />
                            Move to…
                        </DropdownMenuItem>
                    ) : null}
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
