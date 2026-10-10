import { useActions, useValues } from 'kea'

import { IconPlusSmall } from '@posthog/icons'
import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, DropdownMenuSeparator, Skeleton } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { FlatNavMenuLinkItem } from './FlatNavMenuLinkItem'
import { FlatNavProductLinkMenuItems } from './FlatNavProductLinkMenuItems'

export function FlatNavDashboardsMenuItems(): JSX.Element {
    const { pinnedDashboards, dashboardsLoading, loadDashboardsFailed } = useValues(dashboardsModel)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    useOnMountEffect(() => {
        loadDashboardsIfNeeded()
    })

    return (
        <>
            <DropdownMenuGroup>
                {/* The same link search uses. The dashboards scene reads the hash when it mounts, so the modal opens from any page */}
                <FlatNavMenuLinkItem
                    to={`${urls.dashboards()}#newDashboard=modal`}
                    icon={<IconPlusSmall />}
                    data-attr="flat-nav-dashboards-menu-new-dashboard"
                >
                    New dashboard
                </FlatNavMenuLinkItem>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <DropdownMenuGroup>
                <DropdownMenuLabel>Pinned dashboards</DropdownMenuLabel>
                {/* A failed load leaves dashboardsLoading true for good, so it has to be read first */}
                {loadDashboardsFailed ? (
                    <DropdownMenuItem disabled>Couldn't load dashboards</DropdownMenuItem>
                ) : dashboardsLoading ? (
                    <Skeleton className="mx-2 my-1 h-4" />
                ) : pinnedDashboards.length === 0 ? (
                    <DropdownMenuItem disabled>No pinned dashboards</DropdownMenuItem>
                ) : (
                    pinnedDashboards.map((dashboard) => (
                        <FlatNavMenuLinkItem
                            key={dashboard.id}
                            to={urls.dashboard(dashboard.id)}
                            data-attr="flat-nav-dashboards-menu-pinned-dashboard"
                        >
                            {dashboard.name}
                        </FlatNavMenuLinkItem>
                    ))
                )}
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            <FlatNavProductLinkMenuItems productPath="Dashboards" href={urls.dashboards()} />
        </>
    )
}
