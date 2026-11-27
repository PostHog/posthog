import { IconDatabase, IconPeople, IconServer, IconShieldLock, IconToggle } from '@posthog/icons'
import { DropdownMenuItem, DropdownMenuSub, DropdownMenuSubContent, DropdownMenuSubTrigger } from '@posthog/quill'

import { urls } from 'scenes/urls'

import { todayMenuLinkItem } from './todayMenuLinkItem'

export function TodayStaffSubMenu(): JSX.Element {
    return (
        <DropdownMenuSub>
            <DropdownMenuSubTrigger data-attr="today-rail-staff-menu">Staff</DropdownMenuSubTrigger>
            <DropdownMenuSubContent>
                <DropdownMenuItem
                    render={todayMenuLinkItem('/admin/', { disableClientSideRouting: true })}
                    data-attr="today-rail-django-admin"
                >
                    <IconShieldLock />
                    Django admin
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.instanceStatus())}
                    data-attr="today-rail-instance-panel"
                >
                    <IconServer />
                    Instance panel
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.featureFlagsStaffTools())}
                    data-attr="today-rail-flags-staff-tools"
                >
                    <IconToggle />
                    Flags staff tools
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.cohortsStaffTools())}
                    data-attr="today-rail-cohorts-staff-tools"
                >
                    <IconPeople />
                    Cohorts staff tools
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.experimentsStaffTools())}
                    data-attr="today-rail-experiments-staff-tools"
                >
                    <IconDatabase />
                    Experiments staff tools
                </DropdownMenuItem>
            </DropdownMenuSubContent>
        </DropdownMenuSub>
    )
}
