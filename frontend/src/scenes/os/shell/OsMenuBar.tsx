import { useActions, useValues } from 'kea'

import { IconNotification, IconSparkles } from '@posthog/icons'

import { Logo } from 'lib/brand'
import { AccountMenu } from 'lib/components/Account/AccountMenu'
import { ProjectMenu } from 'lib/components/Account/ProjectMenu'
import { NotificationsPanel } from 'lib/components/NotificationsMenu/NotificationsPanel'
import { IconWithCount } from 'lib/lemon-ui/icons'
import { LemonDropdown } from 'lib/lemon-ui/LemonDropdown'
import { LemonMenu, LemonMenuItems } from 'lib/lemon-ui/LemonMenu'
import { ProfilePicture } from 'lib/lemon-ui/ProfilePicture'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { sidePanelNotificationsLogic } from '~/layout/navigation-3000/sidepanel/panels/activity/sidePanelNotificationsLogic'

import { OsAppMenu } from './OsAppMenu'
import { OsMenuBarSearch } from './OsMenuBarSearch'
import { osShellLogic } from './osShellLogic'

function openInNewTab(href: string): void {
    window.open(href, '_blank', 'noopener,noreferrer')
}

/**
 * The top menu bar, ported from the posthog.com taskbar: the PostHog menu and the focused app's menu on
 * the left, the search in the middle, and the project, PostHog AI, notifications and account on the right.
 */
export function OsMenuBar(): JSX.Element {
    const { openApp } = useActions(osShellLogic)
    const { user } = useValues(userLogic)
    const { inAppUnreadCount } = useValues(sidePanelNotificationsLogic)

    const logoMenu: LemonMenuItems = [
        {
            items: [
                {
                    label: 'Home',
                    onClick: () => openApp(urls.projectHomepage(), 'Home'),
                    'data-attr': 'os-menu-logo-home',
                },
                {
                    label: 'App Store',
                    onClick: () => openApp(urls.osAppStore(), 'App Store'),
                    'data-attr': 'os-menu-apps-store',
                },
                {
                    label: 'Choose desktop apps',
                    onClick: () => openApp(urls.settings('user-navigation'), 'Settings'),
                    'data-attr': 'os-menu-apps-customize',
                },
                {
                    label: 'Settings',
                    onClick: () => openApp(urls.settings(), 'Settings'),
                    'data-attr': 'os-menu-logo-settings',
                },
            ],
        },
        {
            items: [
                {
                    label: 'About PostHog',
                    onClick: () => openInNewTab('https://posthog.com/about'),
                    'data-attr': 'os-menu-logo-about',
                },
            ],
        },
    ]

    return (
        <header className="OsShell__menu-bar" data-os-scheme="primary" data-attr="os-menu-bar">
            <nav aria-label="Menu bar" className="flex items-center gap-px min-w-0">
                <LemonMenu items={logoMenu} placement="bottom-start">
                    <button
                        type="button"
                        className="OsShell__menu-trigger shrink-0"
                        aria-label="PostHog menu"
                        data-attr="os-menu-logo"
                    >
                        {/* Fills a 24px box like the posthog.com mark, so it keeps its aspect ratio. */}
                        <span className="inline-flex w-6 [&_svg]:w-full [&_svg]:h-auto">
                            <Logo layout="logomark" variant="mono" color="currentColor" />
                        </span>
                    </button>
                </LemonMenu>
                <OsAppMenu />
            </nav>
            <OsMenuBarSearch />
            <div data-os-scheme="secondary" className="flex items-center justify-end gap-0.5 py-1 min-w-0">
                <ProjectMenu buttonProps={{ className: 'OsShell__menu-trigger font-semibold min-w-0' }} />
                <Tooltip title="PostHog AI">
                    <button
                        type="button"
                        className="OsShell__menu-trigger"
                        aria-label="PostHog AI"
                        onClick={() => openApp(urls.ai(), 'PostHog AI')}
                        data-attr="os-menu-ai"
                    >
                        <IconSparkles className="size-5" />
                    </button>
                </Tooltip>
                <LemonDropdown
                    overlay={
                        <div className="flex flex-col w-96 h-[70vh]">
                            <NotificationsPanel layout="inline" />
                        </div>
                    }
                    placement="bottom-end"
                >
                    <button
                        type="button"
                        className="OsShell__menu-trigger"
                        aria-label="Notifications"
                        data-attr="os-menu-notifications"
                    >
                        <IconWithCount count={inAppUnreadCount} size="xsmall">
                            <IconNotification className="size-5" />
                        </IconWithCount>
                    </button>
                </LemonDropdown>
                <AccountMenu
                    align="end"
                    trigger={
                        <button
                            type="button"
                            className="OsShell__menu-trigger"
                            aria-label="Account"
                            data-attr="os-menu-account"
                        >
                            <ProfilePicture user={user} size="md" />
                        </button>
                    }
                />
            </div>
        </header>
    )
}
