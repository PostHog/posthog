import { useValues } from 'kea'
import { router } from 'kea-router'

import { IconChevronRight } from '@posthog/icons'

import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import {
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
    onLinkClick,
}: CustomMenuProps): JSX.Element {
    const { pinnedDashboards, dashboardsLoading } = useValues(dashboardsModel)

    return (
        <>
            {pinnedDashboards.length > 0 ? (
                <MenuSub>
                    <MenuSubTrigger asChild>
                        <ButtonPrimitive menuItem>
                            Pinned dashboards
                            <IconChevronRight className="ml-auto size-3" />
                        </ButtonPrimitive>
                    </MenuSubTrigger>

                    <MenuSubContent>
                        {pinnedDashboards.map((dashboard) => (
                            <MenuItem asChild key={dashboard.id}>
                                <Link
                                    buttonProps={{
                                        menuItem: true,
                                    }}
                                    to={urls.dashboard(dashboard.id)}
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
                        ))}
                    </MenuSubContent>
                </MenuSub>
            ) : dashboardsLoading ? (
                <MenuItem disabled>
                    <ButtonPrimitive menuItem>Loading...</ButtonPrimitive>
                </MenuItem>
            ) : (
                <MenuItem disabled>
                    <ButtonPrimitive menuItem>No pinned dashboards</ButtonPrimitive>
                </MenuItem>
            )}
        </>
    )
}
