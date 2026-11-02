import { IconApps, IconChat, IconGear, IconHome, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'

import { IconAnalyticsBars } from 'lib/lemon-ui/icons'
import { isMac } from 'lib/utils/dom'

import { TodayNewAnalyticsButton } from './TodayNewAnalyticsButton'
import { TodayNewChatButton } from './TodayNewChatButton'
import type { TodayRailPane } from './todayShellLogic'

export interface TodayPane {
    label: string
    /** The title on top of the pane. The scene header shows it too while the sidebar is hidden. */
    title: string
    icon: JSX.Element
    action?: () => JSX.Element
}

export const TODAY_PANES: Record<TodayRailPane, TodayPane> = {
    home: { label: 'Home', title: 'Today', icon: <IconHome /> },
    spaces: {
        label: 'Chats',
        title: 'Chats',
        icon: <IconChat />,
        action: TodayNewChatButton,
    },
    analytics: { label: 'Analytics', title: 'Analytics', icon: <IconAnalyticsBars />, action: TodayNewAnalyticsButton },
    products: { label: 'Products', title: 'Products', icon: <IconApps /> },
    settings: { label: 'Settings', title: 'Settings', icon: <IconGear /> },
}

export const TODAY_RAIL_PANES: TodayRailPane[] = ['home', 'spaces', 'analytics', 'products']
export const TODAY_RAIL_FOOTER_PANES: TodayRailPane[] = ['settings']

export function todaySidebarShortcutLabel(): string {
    return isMac() ? '⌘B' : 'Ctrl+B'
}

// The icon names describe the panel, not the click: IconSidebarOpen's arrow points in, so it reads as hide.
export const IconHideSidebar = IconSidebarOpen
export const IconShowSidebar = IconSidebarClose
