import { IconApps, IconChat, IconGear, IconHome, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'

import { IconAnalyticsBars } from 'lib/lemon-ui/icons'
import { isMac } from 'lib/utils/dom'
import { urls } from 'scenes/urls'

import { TodayNewAnalyticsButton } from './TodayNewAnalyticsButton'
import { TodayNewChatButton } from './TodayNewChatButton'
import type { TodayRailPane } from './todayShellLogic'

export interface TodayPane {
    label: string
    /** The title on top of the pane. The scene header shows it too while the sidebar is hidden. */
    title: string
    icon: JSX.Element
    /** The page a rail pick opens. Without one, a pick only opens the sidebar and the open page stays. */
    home?: () => string
    action?: () => JSX.Element
}

export const TODAY_PANES: Record<TodayRailPane, TodayPane> = {
    home: { label: 'Home', title: 'Today', icon: <IconHome />, home: () => urls.projectHomepage() },
    spaces: {
        label: 'Chats',
        title: 'Chats',
        icon: <IconChat />,
        home: () => urls.taskNewSession(),
        action: TodayNewChatButton,
    },
    // No home: like Products, a pick only opens the sidebar and the open page stays.
    analytics: { label: 'Analytics', title: 'Analytics', icon: <IconAnalyticsBars />, action: TodayNewAnalyticsButton },
    products: { label: 'Products', title: 'Products', icon: <IconApps /> },
    settings: { label: 'Settings', title: 'Settings', icon: <IconGear />, home: () => urls.settings('project') },
}

export const TODAY_RAIL_PANES: TodayRailPane[] = ['home', 'spaces', 'analytics', 'products']
export const TODAY_RAIL_FOOTER_PANES: TodayRailPane[] = ['settings']

export function todaySidebarShortcutLabel(): string {
    return isMac() ? '⌘B' : 'Ctrl+B'
}

// The icon names describe the panel, not the click: IconSidebarOpen's arrow points in, so it reads as hide.
export const IconHideSidebar = IconSidebarOpen
export const IconShowSidebar = IconSidebarClose
