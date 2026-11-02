import { useActions, useValues } from 'kea'

import { IconDatabase, IconLeave, IconPeople, IconServer, IconShieldLock, IconToggle } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { todayMenuLinkItem } from './todayMenuLinkItem'

export function TodayAccountMenu(): JSX.Element {
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { isAccountMenuOpen } = useValues(newAccountMenuLogic)
    const { setAccountMenuOpen } = useActions(newAccountMenuLogic)

    return (
        <DropdownMenu open={isAccountMenuOpen} onOpenChange={setAccountMenuOpen}>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label="Account menu"
                        className="size-10 rounded-md data-[popup-open]:bg-[var(--fill-selected)]"
                        data-attr="new-account-menu-button"
                    >
                        <ProfilePicture user={user} size="md" />
                    </Button>
                }
            />
            <DropdownMenuContent side="right" align="end" className="w-64">
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.settings(user?.organization?.id ? 'user' : 'user-danger-zone'))}
                    className="h-auto"
                    data-attr="today-rail-user-settings"
                >
                    <ProfilePicture user={user} size="xs" />
                    <span className="flex min-w-0 flex-col">
                        <span className="truncate font-semibold">{user?.first_name}</span>
                        <span className="truncate text-xs text-muted-foreground">{user?.email}</span>
                    </span>
                </DropdownMenuItem>
                {user?.is_staff && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>Staff</DropdownMenuLabel>
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
                        </DropdownMenuGroup>
                    </>
                )}
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={() => logout()} data-attr="new-account-menu-logout-button">
                    <IconLeave />
                    Log out
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
