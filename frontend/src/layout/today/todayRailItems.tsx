import { IconGear, IconSidebarClose, IconSidebarOpen } from '@posthog/icons'

import { isMac } from 'lib/utils/dom'

import { IconTodayAnalytics } from './rail-icons/IconTodayAnalytics'
import { IconTodayAutomate } from './rail-icons/IconTodayAutomate'
import { IconTodayChats } from './rail-icons/IconTodayChats'
import { IconTodayData } from './rail-icons/IconTodayData'
import { IconTodayHome } from './rail-icons/IconTodayHome'
import { IconTodayMonitor } from './rail-icons/IconTodayMonitor'
import { IconTodayPeople } from './rail-icons/IconTodayPeople'
import { IconTodayProducts } from './rail-icons/IconTodayProducts'
import { IconTodayRelease } from './rail-icons/IconTodayRelease'
import { TodayNewAnalyticsButton } from './TodayNewAnalyticsButton'
import { TodayNewChatButton } from './TodayNewChatButton'
import { TodayNewPeopleButton } from './TodayNewPeopleButton'
import type { TodayRailPane } from './todayShellLogic'

export interface TodayPane {
    label: string
    /** The title on top of the pane. The scene header shows it too while the sidebar is hidden. */
    title: string
    icon: JSX.Element
    action?: () => JSX.Element
}

export const TODAY_PANES: Record<TodayRailPane, TodayPane> = {
    home: { label: 'Home', title: 'Home', icon: <IconTodayHome /> },
    spaces: {
        label: 'Chats',
        title: 'Chats',
        icon: <IconTodayChats />,
        action: TodayNewChatButton,
    },
    analytics: {
        label: 'Analytics',
        title: 'Analytics',
        icon: <IconTodayAnalytics />,
        action: TodayNewAnalyticsButton,
    },
    monitor: { label: 'Monitor', title: 'Monitor', icon: <IconTodayMonitor /> },
    people: { label: 'People', title: 'People', icon: <IconTodayPeople />, action: TodayNewPeopleButton },
    release: { label: 'Release', title: 'Release', icon: <IconTodayRelease /> },
    automate: { label: 'Automate', title: 'Automate', icon: <IconTodayAutomate /> },
    data: { label: 'Data', title: 'Data', icon: <IconTodayData /> },
    products: { label: 'Products', title: 'Products', icon: <IconTodayProducts /> },
    settings: { label: 'Settings', title: 'Settings', icon: <IconGear /> },
}

export function todaySidebarShortcutLabel(): string {
    return isMac() ? '⌘B' : 'Ctrl+B'
}

// The icon names describe the panel, not the click: IconSidebarOpen's arrow points in, so it reads as hide.
export const IconHideSidebar = IconSidebarOpen
export const IconShowSidebar = IconSidebarClose
