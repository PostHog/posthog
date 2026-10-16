import {
    IconApps,
    IconChat,
    IconGear,
    IconGridMasonry,
    IconHome,
    IconSidebarClose,
    IconSidebarOpen,
} from '@posthog/icons'

import { isMac } from 'lib/utils/dom'
import { urls } from 'scenes/urls'

import { TodayNewChatButton } from './TodayNewChatButton'
import { TodayNewViewButton } from './TodayNewViewButton'
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
    views: { label: 'Views', title: 'Views', icon: <IconGridMasonry />, action: TodayNewViewButton },
    products: { label: 'Products', title: 'Products', icon: <IconApps /> },
    settings: { label: 'Settings', title: 'Settings', icon: <IconGear />, home: () => urls.settings('project') },
}

export const TODAY_RAIL_PANES: TodayRailPane[] = ['home', 'spaces', 'views', 'products']
export const TODAY_RAIL_FOOTER_PANES: TodayRailPane[] = ['settings']

export function todaySidebarShortcutLabel(): string {
    return isMac() ? '⌘B' : 'Ctrl+B'
}

// The icon names describe the panel, not the click: IconSidebarOpen's arrow points in, so it reads as hide.
export const IconHideSidebar = IconSidebarOpen
export const IconShowSidebar = IconSidebarClose
