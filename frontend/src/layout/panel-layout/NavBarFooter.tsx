import { IconDownload, IconGear } from '@posthog/icons'
import { Link } from '@posthog/lemon-ui'

import { DebugNotice } from 'lib/components/DebugNotice'
import { HealthMenu } from 'lib/components/HealthMenu/HealthMenu'
import { HelpMenu } from 'lib/components/HelpMenu/HelpMenu'
import { NavPanelAdvertisement } from 'lib/components/NavPanelAdvertisement/NavPanelAdvertisement'
import { NotificationsMenu } from 'lib/components/NotificationsMenu/NotificationsMenu'
import { PosthogStatusShownOnlyIfNotOperational } from 'lib/components/PosthogStatus/PosthogStatusShownOnlyIfNotOperational'
import { useFeatureFlag } from 'lib/hooks/useFeatureFlag'
import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

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
                <Link
                    to={urls.exports()}
                    buttonProps={{ menuItem: isLayoutNavCollapsed ? false : true }}
                    tooltip={isLayoutNavCollapsed ? 'Exports' : undefined}
                    tooltipPlacement="right"
                    data-attr="navbar-exports-button"
                >
                    <IconDownload />
                    {!isLayoutNavCollapsed && 'Exports'}
                </Link>
                <HealthMenu iconOnly={isLayoutNavCollapsed} />
                <HelpMenu iconOnly={isLayoutNavCollapsed} />
                <PosthogStatusShownOnlyIfNotOperational iconOnly={isLayoutNavCollapsed} />
            </div>
        </div>
    )
}
