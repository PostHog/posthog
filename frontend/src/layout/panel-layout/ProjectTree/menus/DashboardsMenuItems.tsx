import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight, IconPlusSmall } from '@posthog/icons'

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

    return (
        <>
            <MenuItem
                asChild
                onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                        onLinkClick?.(true)
                    }
                }}
            >
                {/* The dashboards scene reads the hash when it mounts, so the modal opens from any page */}
                <Link
                    buttonProps={{ menuItem: true }}
                    to={`${urls.dashboards()}#newDashboard=modal`}
                    onClick={() => onLinkClick?.(false)}
                    data-attr="tree-item-menu-new-dashboard"
                >
                    <IconPlusSmall />
                    New dashboard
                </Link>
            </MenuItem>
            <MenuSub
                onOpenChange={(open) => {
                    if (open) {
                        loadDashboardsIfNeeded()
                    }
                }}
            >
                <MenuSubTrigger asChild>
                    <ButtonPrimitive menuItem data-attr="tree-item-menu-pinned-dashboards">
                        Pinned dashboards
                        <IconChevronRight className="ml-auto size-3" />
                    </ButtonPrimitive>
                </MenuSubTrigger>

                {/* Matches the parent menu's width, so long dashboard names truncate instead of widening it */}
                <MenuSubContent className="max-w-[250px]">
                    <MenuGroup>
                        {/* A failed load leaves dashboardsLoading true for good, so it has to be read first */}
                        {loadDashboardsFailed ? (
                            <MenuItem disabled>
                                <ButtonPrimitive menuItem>Couldn't load dashboards</ButtonPrimitive>
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
                                        data-attr="tree-item-menu-pinned-dashboard"
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
