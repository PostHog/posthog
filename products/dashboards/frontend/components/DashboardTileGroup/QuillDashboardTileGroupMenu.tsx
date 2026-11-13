import { useActions } from 'kea'

import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { dashboardsModel } from '~/models/dashboardsModel'

import { type DashboardTileGroupMenuActions, TILE_GROUP_MENU_ITEMS } from './DashboardTileGroupMenuOverlay'
import { QuillDashboardTileGroupMenuItems } from './QuillDashboardTileGroupMenuItems'

export function QuillDashboardTileGroupMenu(actions: DashboardTileGroupMenuActions): JSX.Element {
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    const { copyNoun } = TILE_GROUP_MENU_ITEMS[actions.groupDisplay]

    return (
        <DropdownMenu onOpenChange={(open) => open && actions.onCopyToDashboard && loadDashboardsIfNeeded()}>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon-sm"
                        aria-label="Group actions"
                        tooltip="Group actions"
                        loading={actions.copyLoading}
                        disabledReason={actions.copyLoading ? `Copying ${copyNoun}` : undefined}
                        data-attr="dashboard-tile-group-menu"
                    />
                }
            >
                <IconEllipsis />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="min-w-48">
                <QuillDashboardTileGroupMenuItems {...actions} />
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
