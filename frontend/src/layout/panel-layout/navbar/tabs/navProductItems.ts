import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { DEFINITIONS_TABS } from 'scenes/data-management/definitionsSceneTabsLogic'
import { urls } from 'scenes/urls'

import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { getDefaultTreeData, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
import { POPULAR_CATEGORY, POPULAR_PRODUCT_PATHS } from './productsCatalog'

// These pages are tabs of Event definitions, so the sidebar lists only that entry for them.
const DEFINITIONS_TAB_HREFS = new Set(DEFINITIONS_TABS.filter((tab) => tab.key !== 'events').map((tab) => tab.url))

// Items in this category sit above Starred and All products, so they are never starred or grouped.
export const PINNED_CATEGORY = 'Project'

export function getNavProductItems(featureFlags: FeatureFlagsSet): FileSystemImport[] {
    const items: FileSystemImport[] = [
        {
            path: 'Home',
            category: PINNED_CATEGORY,
            iconType: 'home',
            href: urls.projectRoot(),
            visualOrder: 0,
        },
        {
            path: 'Activity',
            category: PINNED_CATEGORY,
            iconType: 'activity',
            href: urls.activity(ActivityTab.ExploreEvents),
            visualOrder: 2,
        },
        {
            path: 'Persons',
            displayLabel: 'People and groups',
            category: PINNED_CATEGORY,
            iconType: 'persons',
            href: urls.persons(),
            visualOrder: 3,
        },
        ...getDefaultTreeProducts().map(
            (item): FileSystemImport =>
                item.href === urls.inbox()
                    ? {
                          ...item,
                          displayLabel: 'Self-driving',
                          category: PINNED_CATEGORY,
                          visualOrder: 1,
                      }
                    : item
        ),
        ...getDefaultTreeData(),
    ]
    const destinations = new Map<string, FileSystemImport>()
    for (const item of items) {
        if (
            !item.href ||
            DEFINITIONS_TAB_HREFS.has(item.href) ||
            (item.flag && !featureFlags[item.flag as keyof FeatureFlagsSet])
        ) {
            continue
        }
        const existing = destinations.get(item.href)
        destinations.set(item.href, existing ? { ...item, ...existing } : item)
    }
    return [...destinations.values()].map((item) =>
        POPULAR_PRODUCT_PATHS.includes(item.path) ? { ...item, category: POPULAR_CATEGORY } : item
    )
}
