import { IconPinFilled } from '@posthog/icons'
import { useValues } from 'kea'
import { router } from 'kea-router'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator } from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { CustomMenuProps } from '../types'

export function DashboardsMenuItems({ MenuItem = DropdownMenuItem, onLinkClick }: CustomMenuProps): JSX.Element {
    const { pinnedDashboards, dashboardsLoading } = useValues(dashboardsModel)

    return (
        <>
            <DropdownMenuLabel>Pinned dashboards</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {pinnedDashboards.length > 0 ? (
                pinnedDashboards.map((dashboard) => (
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
                            <IconPinFilled className="size-3 text-tertiary" />
                            <span className="truncate">{dashboard.name}</span>
                        </Link>
                    </MenuItem>
                ))
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
