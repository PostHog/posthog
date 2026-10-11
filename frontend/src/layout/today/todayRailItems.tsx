import { IconApps, IconChat, IconGridMasonry, IconHome } from '@posthog/icons'

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
