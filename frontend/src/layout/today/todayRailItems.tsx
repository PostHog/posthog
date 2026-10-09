import { IconApps, IconChat, IconGridMasonry, IconHome, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'

import { isMac } from 'lib/utils/dom'

import { TodayRailPane } from './todayShellLogic'

export interface TodayRailItem {
    pane: TodayRailPane
    label: string
    icon: JSX.Element
}

export const TODAY_RAIL_ITEMS: TodayRailItem[] = [
    { pane: 'home', label: 'Home', icon: <IconHome /> },
    { pane: 'spaces', label: 'Chats', icon: <IconChat /> },
    { pane: 'views', label: 'Views', icon: <IconGridMasonry /> },
    { pane: 'products', label: 'Products', icon: <IconApps /> },
]

/** The title on top of each pane. The scene header shows the same title while the sidebar is hidden. */
export const TODAY_PANE_TITLES: Record<TodayRailPane, string> = {
    home: 'Today',
    spaces: 'Chats',
    views: 'Views',
    products: 'Products',
}

export function todaySidebarShortcutLabel(): string {
    return isMac() ? '⌘B' : 'Ctrl+B'
}

// The icon names describe the panel, not the click: IconSidebarOpen's arrow points in, so it reads as hide.
export const IconHideSidebar = IconSidebarOpen
export const IconShowSidebar = IconSidebarClose
