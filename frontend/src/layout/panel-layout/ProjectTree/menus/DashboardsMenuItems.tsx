import { useActions, useValues } from 'kea'
import { combineUrl, router } from 'kea-router'

import { IconChevronRight } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
} from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { CustomMenuProps } from '../types'

const PINNED_DASHBOARDS_URL = combineUrl(urls.dashboards(), { pinned: true }).url

export function DashboardsMenuItems({
    MenuItem = DropdownMenuItem,
    MenuSub = DropdownMenuSub,
    MenuSubTrigger = DropdownMenuSubTrigger,
    MenuSubContent = DropdownMenuSubContent,
    MenuGroup = DropdownMenuGroup,
    onLinkClick,
}: CustomMenuProps): JSX.Element {
    const { pinnedDashboards, dashboardsLoading, loadDashboardsFailed } = useValues(dashboardsModel)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)
    const emptyMessage = loadDashboardsFailed
        ? "Couldn't load dashboards. Reopen this menu to retry."
        : dashboardsLoading
          ? 'Loading...'
          : pinnedDashboards.length === 0
            ? 'No pinned dashboards'
            : null

    return (
        <>
            <MenuSub
                onOpenChange={(open) => {
                    if (open) {
                        loadDashboardsIfNeeded()
                    }
                }}
            >
                <MenuSubTrigger asChild>
                    <Link
                        buttonProps={{
                            menuItem: true,
                        }}
                        to={PINNED_DASHBOARDS_URL}
                        onClick={() => onLinkClick?.(false)}
                    >
                        Pinned dashboards
                        <IconChevronRight className="ml-auto size-3" />
                    </Link>
                </MenuSubTrigger>

                <MenuSubContent>
                    <MenuGroup>
                        {emptyMessage ? (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>{emptyMessage}</ButtonPrimitive>
                            </MenuItem>
                        ) : (
                            pinnedDashboards.map((dashboard) => (
                                <MenuItem asChild key={dashboard.id}>
                                    <Link
                                        buttonProps={{
                                            menuItem: true,
                                        }}
                                        to={urls.dashboard(dashboard.id)}
                                        tooltip={dashboard.name}
                                        tooltipPlacement="right"
                                        onClick={(e) => {
                                            e.stopPropagation()
                                            onLinkClick?.(false)
                                            router.actions.push(urls.dashboard(dashboard.id))
                                        }}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' || e.key === ' ') {
                                                onLinkClick?.(true)
                                            }
                                        }}
                                    >
                                        <span className="truncate">{dashboard.name}</span>
                                    </Link>
                                </MenuItem>
                            ))
                        )}
                    </MenuGroup>
                </MenuSubContent>
            </MenuSub>
        </>
    )
}
