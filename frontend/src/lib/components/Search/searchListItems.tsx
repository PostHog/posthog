import { router } from 'kea-router'

import {
    IconBell,
    IconClock,
    IconDownload,
    IconLeave,
    IconNotification,
    IconSupport,
    IconTerminal,
} from '@posthog/icons'

import type { FeatureFlagsSet } from 'lib/logic/featureFlagLogic'
import { getProductAccessDisabledReason } from 'lib/utils/accessControlUtils'
import { isFileSystemImportFlagEnabled } from 'lib/utils/fileSystemImportFlags'
import { removeProjectIdIfPresent } from 'lib/utils/kea-router'
import { PLACEHOLDER_HREF } from 'lib/utils/navigateToHref'
import { newInternalTab } from 'lib/utils/newInternalTab'
import { urls } from 'scenes/urls'
import { userLogic } from 'scenes/userLogic'

import { isDefinitionsTabHref } from '~/layout/panel-layout/navbar/tabs/navProductItems'
import { getDefaultTreePersons } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { getTreeItemsMetadata, getTreeItemsNew, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import { SearchItem, fileSystemEntryToSearchItem } from './searchItems'
import { SEARCH_TAB_CATEGORY } from './utils'

/** Max starred shortcuts shown in quick search (folders excluded). */
export const STARRED_LIMIT = 20

type SceneViews = Record<string, string>

interface FixedSearchItem extends SearchItem {
    sceneKey?: string
}

const CATEGORY_SEARCH_KEYWORDS: Record<string, string[]> = {
    CDP: ['data pipelines', 'data pipeline', 'pipeline'],
}

const fixedItem = (
    id: string,
    name: string,
    category: string,
    fields: Partial<FixedSearchItem> = {}
): FixedSearchItem => ({ id, name, displayName: name, category, itemType: null, ...fields })

const lastViewedAt = (sceneKey: string | undefined, sceneViews: SceneViews): string | null =>
    sceneKey ? (sceneViews[sceneKey] ?? null) : null

const withLastViewed = ({ sceneKey, ...item }: FixedSearchItem, sceneViews: SceneViews): SearchItem =>
    sceneKey ? { ...item, lastViewedAt: lastViewedAt(sceneKey, sceneViews) } : item

/** Most recently viewed first. Items never viewed go last, by name. */
const byLastViewed = (a: SearchItem, b: SearchItem): number => {
    if (!a.lastViewedAt && !b.lastViewedAt) {
        return a.name.localeCompare(b.name)
    }
    if (!a.lastViewedAt) {
        return 1
    }
    if (!b.lastViewedAt) {
        return -1
    }
    return Date.parse(b.lastViewedAt) - Date.parse(a.lastViewedAt)
}

const isFlagOn = (flag: string | undefined, featureFlags: FeatureFlagsSet): boolean =>
    !flag || !!(featureFlags as Record<string, boolean>)[flag]

const visibleImports = (
    items: FileSystemImport[],
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean
): FileSystemImport[] =>
    items.filter(
        (item) =>
            (showUnreleased || item.category !== 'Unreleased') && isFileSystemImportFlagEnabled(item, featureFlags)
    )

const withUniqueHref = (items: FileSystemImport[]): FileSystemImport[] => {
    const seen = new Set<string>()
    return items.filter((item) => {
        if (!item.href || seen.has(item.href)) {
            return false
        }
        seen.add(item.href)
        return true
    })
}

const importToSearchItem = (
    item: FileSystemImport,
    fields: Pick<SearchItem, 'id' | 'category'> & Partial<SearchItem>
): SearchItem => ({
    name: item.path,
    displayName: item.path,
    productCategory: item.category || null,
    href: item.href || PLACEHOLDER_HREF,
    itemType: item.iconType || item.type || null,
    record: { type: item.type || item.iconType, iconType: item.iconType, iconColor: item.iconColor },
    ...fields,
})

const tabSearchItems = (
    parents: SearchItem[],
    sources: FileSystemImport[],
    featureFlags: FeatureFlagsSet
): SearchItem[] => {
    const tabsByPath = new Map(sources.map((source) => [source.path, source.searchTabs ?? []]))
    return parents.flatMap((parent) => {
        const parentName = parent.displayName || parent.name
        return (tabsByPath.get(parent.name) ?? [])
            .filter((tab) => isFlagOn(tab.flag, featureFlags))
            .map((tab) => ({
                id: `${parent.id}-tab-${tab.name}`,
                name: `${parentName} ${tab.name}`,
                displayName: tab.name,
                category: SEARCH_TAB_CATEGORY,
                parentName,
                href: tab.href,
                itemType: parent.itemType,
                searchKeywords: tab.searchKeywords,
                disabledReason: parent.disabledReason,
                record: parent.record,
            }))
    })
}

interface DestinationOptions {
    idPrefix: string
    category: string
    featureFlags: FeatureFlagsSet
    sceneViews: SceneViews
    extraItems?: SearchItem[]
}

const destinationSearchItems = (
    sources: FileSystemImport[],
    { idPrefix, category, featureFlags, sceneViews, extraItems = [] }: DestinationOptions
): SearchItem[] => {
    const items = [
        ...sources.map((source) =>
            importToSearchItem(source, {
                id: `${idPrefix}-${source.path}`,
                displayName: source.displayLabel ?? source.path,
                category,
                searchKeywords: [
                    ...(source.category ? (CATEGORY_SEARCH_KEYWORDS[source.category] ?? []) : []),
                    ...(source.searchKeywords ?? []),
                ],
                lastViewedAt: lastViewedAt(source.sceneKey, sceneViews),
                disabledReason: getProductAccessDisabledReason(source),
            })
        ),
        ...extraItems,
    ]
    return [...items, ...tabSearchItems(items, sources, featureFlags)].sort(byLastViewed)
}

/**
 * Format display name:
 * "Insight/Lifecycle" -> "New Lifecycle insight"
 * "Data/Destination" -> "New Destination" (no suffix for Data)
 */
const newItemDisplayName = (path: string): string => {
    const [kind, ...rest] = path.split('/')
    if (!rest.length) {
        return `New ${path}`
    }
    const suffix = kind.toLowerCase()
    return suffix === 'data' ? `New ${rest.join(' ')}` : `New ${rest.join(' ')} ${suffix}`
}

const ACTIVITY_ITEM = fixedItem('product-activity', 'Activity', 'tools', {
    productCategory: null,
    href: urls.activity(ActivityTab.ExploreEvents),
    icon: <IconClock />,
    sceneKey: 'Activity',
    record: { type: 'activity', iconType: undefined, iconColor: undefined },
})

// Blank SQL query in a new browser tab (inheriting the active warehouse connection when
// triggered from within the SQL editor). Scoped to the command palette: it relies on
// onSelect + newInternalTab, and only the 'command' Search surface honors onSelect —
// the new-tab scene and AI-first homepage are href-only and would render a dead item.
const NEW_SQL_QUERY_ITEM = fixedItem('new-sql-query-tab', 'New SQL query', 'create', {
    productCategory: null,
    itemType: 'insight/hog',
    searchKeywords: ['sql', 'hogql', 'query', 'blank sql', 'new tab'],
    record: { type: 'insight', iconType: 'insight/hog' },
    onSelect: () => {
        const onSqlEditor = removeProjectIdIfPresent(router.values.location.pathname) === urls.sqlEditor()
        const connectionId = onSqlEditor ? router.values.hashParams?.c : undefined
        newInternalTab(urls.sqlEditor(connectionId ? { connectionId } : {}))
    },
})

const HEALTH_ITEMS = [
    fixedItem('health-pipeline-status', 'Pipeline status', 'health', {
        href: urls.pipelineStatus(),
        itemType: 'pipeline_status',
        sceneKey: 'PipelineStatus',
        record: { type: 'pipeline_status', iconType: 'pipeline_status' },
    }),
    fixedItem('health-sdk-health', 'SDK health', 'health', {
        href: urls.sdkHealth(),
        itemType: 'sdk_health',
        sceneKey: 'SdkHealth',
        record: { type: 'sdk_health', iconType: 'sdk_health' },
    }),
]

const terminalItem = (toggleTerminal: () => void): FixedSearchItem =>
    fixedItem('misc-toggle-terminal', 'Toggle terminal', 'misc', {
        icon: <IconTerminal />,
        searchKeywords: ['terminal', 'shell', 'console'],
        onSelect: toggleTerminal,
        record: { type: 'terminal' },
    })

const MISC_ITEMS = [
    fixedItem('misc-exports', 'Exports', 'misc', {
        href: urls.exports(),
        icon: <IconDownload />,
        sceneKey: 'Exports',
        record: { type: 'exports' },
    }),
    fixedItem('misc-alerts', 'Alerts', 'misc', {
        href: urls.alerts(),
        icon: <IconBell />,
        sceneKey: 'SavedInsights',
        record: { type: 'alerts' },
    }),
    fixedItem('misc-subscriptions', 'Subscriptions', 'misc', {
        href: urls.subscriptions(),
        icon: <IconNotification />,
        sceneKey: 'Subscriptions',
        record: { type: 'subscriptions' },
    }),
    // The user's own tickets with PostHog. The Support product holds tickets from their customers.
    fixedItem('misc-my-tickets', 'Your tickets', 'misc', {
        productCategory: 'PostHog support',
        href: urls.myTickets(),
        icon: <IconSupport />,
        itemType: 'my_tickets',
        searchKeywords: ['my tickets', 'support tickets', 'posthog support', 'contact support', 'support', 'help'],
        sceneKey: 'MyTickets',
        record: { type: 'my_tickets' },
    }),
    fixedItem('misc-logout', 'Log out', 'misc', {
        icon: <IconLeave />,
        searchKeywords: ['logout', 'log out', 'sign out', 'signout', 'exit'],
        onSelect: () => userLogic.actions.logout(),
        record: { type: 'logout' },
    }),
]

export const starredSearchItems = (entries: FileSystemEntry[]): SearchItem[] =>
    entries
        .filter((entry) => entry.type !== 'folder')
        .slice(0, STARRED_LIMIT)
        .map((entry) =>
            fileSystemEntryToSearchItem(entry, {
                id: `starred-${entry.id}`,
                category: 'starred',
                searchKeywords: ['starred', 'favorite', 'favourite', 'shortcut'],
            })
        )

export const productSearchItems = (
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean,
    sceneViews: SceneViews
): SearchItem[] => {
    const sources = withUniqueHref(
        visibleImports(
            [...getTreeItemsProducts(), ...getTreeItemsMetadata().filter((item) => !isDefinitionsTabHref(item.href))],
            featureFlags,
            showUnreleased
        )
    )
    return destinationSearchItems(sources, {
        idPrefix: 'product',
        category: 'tools',
        featureFlags,
        sceneViews,
        extraItems: [withLastViewed(ACTIVITY_ITEM, sceneViews)],
    })
}

export const dataManagementSearchItems = (
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean,
    sceneViews: SceneViews
): SearchItem[] => {
    const sources = visibleImports(
        getTreeItemsMetadata().filter((item) => isDefinitionsTabHref(item.href)),
        featureFlags,
        showUnreleased
    )
    return destinationSearchItems(sources, {
        idPrefix: 'data-management',
        category: 'data-management',
        featureFlags,
        sceneViews,
    })
}

export const newSearchItems = (
    featureFlags: FeatureFlagsSet,
    showUnreleased: boolean,
    commandPalette: boolean
): SearchItem[] => [
    ...visibleImports(getTreeItemsNew(), featureFlags, showUnreleased).map((item) => {
        const displayName = newItemDisplayName(item.path)
        return importToSearchItem(item, {
            id: `new-${item.path}`,
            name: displayName,
            displayName,
            category: 'create',
            hiddenSearchText: [displayName, item.path, item.type, item.iconType].filter(Boolean).join(' '),
        })
    }),
    ...(commandPalette ? [NEW_SQL_QUERY_ITEM] : []),
]

export const peopleSearchItems = (groupItems: FileSystemImport[], sceneViews: SceneViews): SearchItem[] =>
    [...getDefaultTreePersons(), ...groupItems].map((item) =>
        importToSearchItem(item, {
            id: `people-${item.path}`,
            category: 'people',
            lastViewedAt: lastViewedAt(item.sceneKey, sceneViews),
        })
    )

export const healthSearchItems = (sceneViews: SceneViews): SearchItem[] =>
    HEALTH_ITEMS.map((item) => withLastViewed(item, sceneViews))

export const miscSearchItems = (sceneViews: SceneViews, toggleTerminal: (() => void) | null): SearchItem[] =>
    [...(toggleTerminal ? [terminalItem(toggleTerminal)] : []), ...MISC_ITEMS].map((item) =>
        withLastViewed(item, sceneViews)
    )
