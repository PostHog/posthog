import { OverviewItem } from 'scenes/session-recordings/components/OverviewGrid'

import { PropertyFilterType } from '~/types'

export type OverviewTab = 'session' | 'person' | 'device'

export const OVERVIEW_STAT_LABELS: string[] = ['Duration', 'Clicks', 'Key presses', 'Errors']

// Session properties about the browser, OS, screen or location belong on the Device tab.
const DEVICE_PROPERTY_PREFIXES = [
    '$geoip_',
    '$browser',
    '$os',
    '$device',
    '$screen_',
    '$viewport_',
    '$timezone',
    '$raw_user_agent',
]

export function overviewTabForProperty(property: string, propertyFilterType?: PropertyFilterType): OverviewTab {
    if (DEVICE_PROPERTY_PREFIXES.some((prefix) => property.startsWith(prefix))) {
        return 'device'
    }
    return propertyFilterType === PropertyFilterType.Person ? 'person' : 'session'
}

export function overviewTabForItem(item: OverviewItem): OverviewTab {
    return item.type === 'property' ? overviewTabForProperty(item.property, item.propertyFilterType) : 'session'
}

export function groupOverviewItemsByTab(items: OverviewItem[]): Record<OverviewTab, OverviewItem[]> {
    const grouped: Record<OverviewTab, OverviewItem[]> = { session: [], person: [], device: [] }
    for (const item of items) {
        grouped[overviewTabForItem(item)].push(item)
    }
    return grouped
}
