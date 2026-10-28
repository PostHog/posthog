import { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { isFileSystemImportFlagEnabled } from 'lib/utils/fileSystemImportFlags'
import { DEFINITIONS_TABS } from 'scenes/data-management/definitionsSceneTabsLogic'
import { isWelcomeNavItemShown } from 'scenes/onboarding/welcome/welcomeNavItem'
import { urls } from 'scenes/urls'

import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { getDefaultTreeData, getDefaultTreeProducts } from '../../ProjectTree/defaultTree'
import {
    POPULAR_CATEGORY,
    POPULAR_PRODUCT_PATHS,
    ProductsItemGroup,
    groupProducts,
    productMatchesSearch,
} from './productsCatalog'

// These pages are tabs of Event definitions, so the sidebar lists only that entry for them.
const DEFINITIONS_TAB_HREFS = new Set(DEFINITIONS_TABS.filter((tab) => tab.key !== 'events').map((tab) => tab.url))

export function isDefinitionsTabHref(href: string | undefined): boolean {
    return !!href && DEFINITIONS_TAB_HREFS.has(href)
}

// Items in this category sit above Starred and All products, so they are never starred or grouped.
export const PINNED_CATEGORY = 'Project'

// Shown first, and only while the project is new on the simple onboarding arm (see `isWelcomeNavItemShown`).
export const WELCOME_NAV_ITEM: FileSystemImport = {
    path: 'Welcome',
    category: PINNED_CATEGORY,
    iconType: 'wizard',
    href: urls.onboardingWelcome(),
    visualOrder: -1,
}

/** Every page the Products tab can list, before feature flags and the Welcome page apply. */
export function getNavProductPages(): FileSystemImport[] {
    return [
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
}

/** `projectCreatedAt` decides whether a new project gets the Welcome page. */
export function getNavProductItems(featureFlags: FeatureFlagsSet, projectCreatedAt?: string): FileSystemImport[] {
    const items = [
        ...(isWelcomeNavItemShown(projectCreatedAt, featureFlags) ? [WELCOME_NAV_ITEM] : []),
        ...getNavProductPages(),
    ]
    const destinations = new Map<string, FileSystemImport>()
    for (const item of items) {
        if (!item.href || isDefinitionsTabHref(item.href) || !isFileSystemImportFlagEnabled(item, featureFlags)) {
            continue
        }
        const existing = destinations.get(item.href)
        destinations.set(item.href, existing ? { ...item, ...existing } : item)
    }
    return [...destinations.values()].map((item) =>
        POPULAR_PRODUCT_PATHS.includes(item.path) ? { ...item, category: POPULAR_CATEGORY } : item
    )
}

export function pinnedNavProducts(items: FileSystemImport[], search: string): FileSystemImport[] {
    return items
        .filter((item) => item.category === PINNED_CATEGORY && productMatchesSearch(item, search))
        .sort((a, b) => (a.visualOrder ?? Infinity) - (b.visualOrder ?? Infinity))
}

export function groupNavProducts(items: FileSystemImport[], search: string): ProductsItemGroup[] {
    return groupProducts(
        items.filter((item) => item.category !== PINNED_CATEGORY),
        search
    )
}

// Session replay opens its home page, but every recording page under /replay/ belongs to it too.
function navProductMatchPath(item: FileSystemImport): string | null {
    return item.path === 'Session replay' ? '/replay' : (item.href?.split(/[?#]/)[0] ?? null)
}

export function navProductHrefForPath(path: string, items: FileSystemImport[]): string | null {
    let match: { href: string; matchPath: string } | null = null
    for (const item of items) {
        const matchPath = navProductMatchPath(item)
        if (
            item.href &&
            matchPath &&
            (path === matchPath || path.startsWith(`${matchPath}/`)) &&
            (!match || matchPath.length > match.matchPath.length)
        ) {
            match = { href: item.href, matchPath }
        }
    }
    return match?.href ?? null
}
