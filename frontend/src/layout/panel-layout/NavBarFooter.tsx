import { IconGear } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { NewAccountMenu } from 'lib/components/Account/NewAccountMenu'
import { DebugNotice } from 'lib/components/DebugNotice'
import { HelpMenu } from 'lib/components/HelpMenu/HelpMenu'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { NotificationsMenu } from 'lib/components/NotificationsMenu/NotificationsMenu'
import { PosthogStatusShownOnlyIfNotOperational } from 'lib/components/PosthogStatus/PosthogStatusShownOnlyIfNotOperational'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { isDesktopApp } from 'lib/utils/isDesktopApp'
import { urls } from 'scenes/urls'

import { InstallationStatusNavButton } from './InstallationStatusNavButton'

export function NavBarFooter({ isLayoutNavCollapsed }: { isLayoutNavCollapsed: boolean }): JSX.Element {
    const isNotificationsEnabled = useFeatureFlag('REAL_TIME_NOTIFICATIONS')

    return (
        <div className="p-1 flex flex-col gap-px items-start pb-2">
            <div
                className={cn('flex flex-col gap-px w-full', {
                    'items-center': isLayoutNavCollapsed,
                })}
            >
                <DebugNotice isCollapsed={isLayoutNavCollapsed} />
            </div>

            <NavPanelAdvertisement />

            <div
                className={cn('flex flex-col gap-px w-full', {
                    'items-center': isLayoutNavCollapsed,
                })}
            >
                {isNotificationsEnabled && <NotificationsMenu iconOnly={isLayoutNavCollapsed} />}
                <InstallationStatusNavButton iconOnly={isLayoutNavCollapsed} />
                <Link
                    to={urls.settings('project')}
                    buttonProps={{ menuItem: isLayoutNavCollapsed ? false : true }}
                    tooltip={isLayoutNavCollapsed ? 'Settings' : undefined}
                    tooltipPlacement="right"
                    data-attr="navbar-settings"
                >
                    <IconGear />
                    {!isLayoutNavCollapsed && 'Settings'}
                </Link>
                <HelpMenu iconOnly={isLayoutNavCollapsed} />
                {/* Desktop app: the org/project switcher lives down here (below "More"), so the
                    top row keeps only the traffic lights and search — like PostHog Code */}
                {isDesktopApp() && <NewAccountMenu isLayoutNavCollapsed={isLayoutNavCollapsed} />}
                <PosthogStatusShownOnlyIfNotOperational iconOnly={isLayoutNavCollapsed} />
            </div>
        </div>
    )
}
