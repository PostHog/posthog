import { IconPinFilled } from '@posthog/icons'
import { useValues } from 'kea'
import { Link } from 'lib/lemon-ui/Link'
import { ButtonPrimitive } from 'lib/ui/Button/ButtonPrimitives'
import { DropdownMenuItem } from 'lib/ui/DropdownMenu/DropdownMenu'
import { urls } from 'scenes/urls'

import { dashboardsModel } from '~/models/dashboardsModel'

import { panelLayoutLogic } from '../../panelLayoutLogic'
import { CustomMenuProps } from '../types'

export function DashboardsMenu({ MenuItem = DropdownMenuItem }: CustomMenuProps): JSX.Element {
    const { pinnedDashboards, dashboardsLoading } = useValues(dashboardsModel)
    const { mainContentRef } = useValues(panelLayoutLogic)

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
                            onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                    // small delay to fight dropdown menu from taking focus
                                    setTimeout(() => {
                                        mainContentRef?.current?.focus()
                                    }, 10)
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
