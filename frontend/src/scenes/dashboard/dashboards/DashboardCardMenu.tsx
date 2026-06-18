import { useActions } from 'kea'
import { router } from 'kea-router'

import { IconCopy, IconEllipsis, IconTrash } from '@posthog/icons'

import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { dashboardsFileSystemLogic } from './dashboardsFileSystemLogic'

// Per-card actions for the grid/finder arms. NOTE: uses lib/ui/DropdownMenu (the proven, app-wide menu)
// rather than @posthog/quill per CLAUDE.md — quill menus have no app precedent yet and their runtime
// rendering is unverified here; converting this to quill is a tracked follow-up.
export function DashboardCardMenu({
    dashboardId,
    dashboardName,
}: {
    dashboardId: number
    dashboardName: string
}): JSX.Element {
    const { cutDashboard, copyDashboard, startRenaming, deleteDashboardWithConfirm } =
        useActions(dashboardsFileSystemLogic)

    return (
        <DropdownMenu>
            <DropdownMenuTrigger asChild>
                <ButtonPrimitive iconOnly aria-label="Dashboard actions">
                    <IconEllipsis className="text-tertiary" />
                </ButtonPrimitive>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" side="bottom">
                <DropdownMenuGroup>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => router.actions.push(urls.dashboard(dashboardId))}>
                            Open
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => startRenaming(dashboardId)}>
                            Rename
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => cutDashboard(dashboardId)}>
                            Cut
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive menuItem onClick={() => copyDashboard(dashboardId)}>
                            <IconCopy />
                            Copy
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                    <DropdownMenuItem asChild>
                        <ButtonPrimitive
                            menuItem
                            variant="danger"
                            onClick={() => deleteDashboardWithConfirm(dashboardId, dashboardName)}
                        >
                            <IconTrash />
                            Delete
                        </ButtonPrimitive>
                    </DropdownMenuItem>
                </DropdownMenuGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
