import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'
import { useEffect } from 'react'

import {
    IconArrowLeft,
    IconDatabase,
    IconLeave,
    IconPeople,
    IconServer,
    IconShieldLock,
    IconToggle,
} from '@posthog/icons'
import { lemonToast } from '@posthog/lemon-ui'
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
import { featurePreviewsLogic } from 'lib/components/FeaturePreviews/featurePreviewsLogic'
import { FEATURE_FLAGS } from 'lib/constants'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture/ProfilePicture'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { todayMenuLinkItem } from './todayMenuLinkItem'

export function TodayAccountMenu(): JSX.Element {
    const { user } = useValues(userLogic)
    const { logout } = useActions(userLogic)
    const { isAccountMenuOpen } = useValues(newAccountMenuLogic)
    const { setAccountMenuOpen } = useActions(newAccountMenuLogic)
    const { earlyAccessFeatures } = useValues(featurePreviewsLogic)
    const { loadEarlyAccessFeatures, updateEarlyAccessFeatureEnrollment } = useActions(featurePreviewsLogic)
    // The stage rides on the enrollment event, so the list loads before the person can click the switch.
    useEffect(() => {
        if (isAccountMenuOpen) {
            loadEarlyAccessFeatures()
        }
    }, [isAccountMenuOpen, loadEarlyAccessFeatures])
    const todayNavFeature = earlyAccessFeatures.find((feature) => feature.flagKey === FEATURE_FLAGS.TODAY_RAIL_NAV)
    // Experiment cohorts must not see the other experience advertised, so the switch rides its own flag.
    const { featureFlags } = useValues(featureFlagLogic)
    const showNavSwitch = !!featureFlags[FEATURE_FLAGS.TODAY_RAIL_NAV_SWITCH]

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
                {showNavSwitch && (
                    <>
                        <DropdownMenuSeparator />
                        <DropdownMenuItem
                            onClick={() => {
                                // pinned: analytics event name and properties. The exit survey triggers on this event.
                                posthog.capture('today nav switched off', { surface: 'account_menu' })
                                updateEarlyAccessFeatureEnrollment(
                                    FEATURE_FLAGS.TODAY_RAIL_NAV,
                                    false,
                                    todayNavFeature?.stage
                                )
                                lemonToast.success(
                                    'You are back on the old navigation. Turn the new navigation on again from the account menu.'
                                )
                            }}
                            data-attr="today-rail-switch-old-nav"
                        >
                            <IconArrowLeft />
                            Switch to the old navigation
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
