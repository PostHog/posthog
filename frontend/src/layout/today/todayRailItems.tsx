import { IconApps, IconChat, IconDatabase, IconGridMasonry, IconHome } from '@posthog/icons'

import { TodayRailPane } from './todayShellLogic'

export interface TodayRailItem {
    pane: TodayRailPane
    label: string
    icon: JSX.Element
}

export const TODAY_RAIL_ITEMS: TodayRailItem[] = [
    { pane: 'home', label: 'Home', icon: <IconHome /> },
    { pane: 'spaces', label: 'Spaces', icon: <IconChat /> },
    { pane: 'views', label: 'Views', icon: <IconGridMasonry /> },
    { pane: 'products', label: 'Products', icon: <IconApps /> },
    { pane: 'warehouse', label: 'Warehouse', icon: <IconDatabase /> },
]

export function withoutWarehouse<T extends TodayRailItem>(items: T[], warehouseEnabled: boolean): T[] {
    return warehouseEnabled ? items : items.filter(({ pane }) => pane !== 'warehouse')
}
