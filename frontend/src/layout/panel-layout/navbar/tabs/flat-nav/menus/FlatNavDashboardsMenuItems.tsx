import { useActions, useValues } from 'kea'

import { DropdownMenuGroup, DropdownMenuItem, DropdownMenuLabel, Skeleton } from '@posthog/quill'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { FlatNavMenuLinkItem } from './FlatNavMenuLinkItem'

export function FlatNavDashboardsMenuItems(): JSX.Element {
    const { pinnedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { loadDashboardsIfNeeded } = useActions(dashboardsModel)

    useOnMountEffect(() => {
        loadDashboardsIfNeeded()
    })

    return (
        <DropdownMenuGroup>
            <DropdownMenuLabel>Pinned dashboards</DropdownMenuLabel>
            {dashboardsLoading ? (
                <Skeleton className="mx-2 my-1 h-4" />
            ) : pinnedDashboards.length === 0 ? (
                <DropdownMenuItem disabled>No pinned dashboards</DropdownMenuItem>
            ) : (
                pinnedDashboards.map((dashboard) => (
                    <FlatNavMenuLinkItem key={dashboard.id} to={urls.dashboard(dashboard.id)}>
                        {dashboard.name}
                    </FlatNavMenuLinkItem>
                ))
            )}
        </DropdownMenuGroup>
    )
}
