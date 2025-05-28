import { IconPinFilled } from '@posthog/icons'
import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { CustomMenuProps } from '../types'

export function DashboardsMenu({ MenuItem, MenuSeparator }: CustomMenuProps): JSX.Element {
    const { pinnedDashboards, dashboardsLoading } = useValues(dashboardsModel)

    return (
        <>
            {pinnedDashboards.length > 0 ? (
                pinnedDashboards.map((dashboard) => (
                    <MenuItem key={dashboard.id} asChild>
                        <Link
                            buttonProps={{
                                menuItem: true,
                            }}
                            to={urls.dashboard(dashboard.id)}
                        >
                            <IconPinFilled className="size-3 text-tertiary" />
                            {dashboard.name}
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
            <MenuSeparator />
        </>
    )
}
