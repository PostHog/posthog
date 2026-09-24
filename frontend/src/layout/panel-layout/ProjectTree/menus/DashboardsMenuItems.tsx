import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

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
    const pinnedDashboardsUrl = `${urls.dashboards()}?pinned=true`

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
                        to={pinnedDashboardsUrl}
                        onClick={() => onLinkClick?.(false)}
                    >
                        Pinned dashboards
                        <IconChevronRight className="ml-auto size-3" />
                    </Link>
                </MenuSubTrigger>

                <MenuSubContent>
                    <MenuGroup>
                        {/* A failed load leaves dashboardsLoading true for good, so it has to be read first */}
                        {loadDashboardsFailed ? (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>
                                    Couldn't load dashboards. Reopen this menu to retry.
                                </ButtonPrimitive>
                            </MenuItem>
                        ) : dashboardsLoading ? (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>Loading...</ButtonPrimitive>
                            </MenuItem>
                        ) : pinnedDashboards.length > 0 ? (
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
                        ) : (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>No pinned dashboards</ButtonPrimitive>
                            </MenuItem>
                        )}
                    </MenuGroup>
                </MenuSubContent>
            </MenuSub>
        </>
    )
}
