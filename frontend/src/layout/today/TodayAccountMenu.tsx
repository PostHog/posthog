import { useActions, useMountedLogic, useValues } from 'kea'

import { IconExternal, IconGear, IconLeave } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuCheckboxItem,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { newAccountMenuLogic } from 'lib/components/Account/newAccountMenuLogic'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { newEventsTableLogic } from '~/layout/navigation/newEventsTableLogic'

import { TodayHelpMenuItems } from './TodayHelpMenuItems'
import { todayHelpMenuRedirectLogic } from './todayHelpMenuRedirectLogic'
import { todayMenuLinkItem } from './todayMenuLinkItem'
import { SEVERITY_INDICATOR } from './todayRailSeverity'
import { todayRailStatusLogic } from './todayRailStatusLogic'
import { todayShellLogic } from './todayShellLogic'
import { TodayStaffSubMenu } from './TodayStaffSubMenu'

/** The account menu, on the rail or in the phone layout's sidebar footer. */
export function TodayAccountMenu({ placement = 'rail' }: { placement?: 'rail' | 'phone-footer' }): JSX.Element {
    useMountedLogic(todayHelpMenuRedirectLogic)
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { isAccountMenuOpen } = useValues(newAccountMenuLogic)
    const { setAccountMenuOpen } = useActions(newAccountMenuLogic)
    const { newEventsTableAvailable, newEventsTableEnabled } = useValues(newEventsTableLogic)
    const { setNewEventsTable, openEventsTableTab } = useActions(newEventsTableLogic)
    const { helpSeverity, helpLabel } = useValues(todayRailStatusLogic)
    const { activePane } = useValues(todayShellLogic)
    const { clickRailPane } = useActions(todayShellLogic)

    return (
        <DropdownMenu open={isAccountMenuOpen} onOpenChange={setAccountMenuOpen}>
            <DropdownMenuTrigger
                render={
                    <Button
                        size="icon"
                        aria-label={helpLabel('Account menu')}
                        indicator={SEVERITY_INDICATOR[helpSeverity]}
                        className="size-10 rounded-md [--quill-button-indicator-ring:var(--chrome)] data-[popup-open]:bg-[var(--fill-selected)]"
                        data-attr="new-account-menu-button"
                    >
                        <ProfilePicture user={user} size="md" />
                    </Button>
                }
            />
            <DropdownMenuContent side={placement === 'phone-footer' ? 'top' : 'right'} align="end" className="w-64">
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.settings(user?.organization?.id ? 'user' : 'user-danger-zone'))}
                    description={user?.email}
                    data-attr="today-rail-user-settings"
                >
                    <ProfilePicture user={user} size="xs" />
                    <span className="truncate font-semibold">{user?.first_name}</span>
                </DropdownMenuItem>
                <DropdownMenuItem
                    render={todayMenuLinkItem(urls.settings('project'))}
                    onClick={(event) => {
                        event.preventDefault()
                        clickRailPane('settings')
                    }}
                    aria-current={activePane === 'settings' ? 'page' : undefined}
                    // pinned: autocapture `data-attr` kept from the Settings rail tile this item replaced.
                    data-attr="today-settings"
                >
                    <IconGear />
                    Settings
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <TodayHelpMenuItems />
                {user?.is_staff && <TodayStaffSubMenu />}
                {newEventsTableAvailable && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuCheckboxItem
                            checked={newEventsTableEnabled}
                            onCheckedChange={setNewEventsTable}
                            data-attr="new-events-table-switch"
                        >
                            New events table
                        </DropdownMenuCheckboxItem>
                        <DropdownMenuItem
                            onClick={() => openEventsTableTab(true)}
                            data-attr="new-events-table-open-new"
                        >
                            <IconExternal />
                            Open this page with new events table
                        </DropdownMenuItem>
                        <DropdownMenuItem
                            onClick={() => openEventsTableTab(false)}
                            data-attr="new-events-table-open-classic"
                        >
                            <IconExternal />
                            Open this page with classic events table
                        </DropdownMenuItem>
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
