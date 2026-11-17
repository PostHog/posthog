import { IconEllipsis } from '@posthog/icons'
import { Button, DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from '@posthog/quill'

import { type DashboardTileGroupMenuActions, TILE_GROUP_MENU_ITEMS } from './DashboardTileGroupMenuOverlay'
import { QuillDashboardTileGroupMenuItems } from './QuillDashboardTileGroupMenuItems'

export function QuillDashboardTileGroupMenu(actions: DashboardTileGroupMenuActions): JSX.Element {
    const { copyNoun } = TILE_GROUP_MENU_ITEMS[actions.groupDisplay]

    return (
        <DropdownMenu>
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
