import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport, ProductItemCategory } from '~/queries/schema/schema-general'
import { FileSystemEntry } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import type { navAppsTabLogicType } from './navAppsTabLogicType'

/**
 * Backs the desktop app's "Apps" navbar tab: one combined, searchable list of the tools
 * (products) and data items, with the user's starred items (file system shortcuts, shared
 * with the project tree's starred mechanism) as a section on top.
 */

export function appsItemName(item: { path: string }): string {
    return unescapePath(splitPath(item.path).pop() ?? item.path)
}

export interface AppsItemGroup {
    label: string
    items: FileSystemImport[]
}

/** Section order in the Apps tab; unknown categories sort after these, alphabetically. */
const APPS_CATEGORY_ORDER: string[] = [
    ProductItemCategory.ANALYTICS,
    ProductItemCategory.AI_ENGINEERING,
    ProductItemCategory.BEHAVIOR,
    ProductItemCategory.APP_MONITORING,
    ProductItemCategory.FEATURES,
    ProductItemCategory.TOOLS,
    ProductItemCategory.UNRELEASED,
    'Groups',
    ProductItemCategory.METADATA,
    'People',
    ProductItemCategory.PIPELINE,
    ProductItemCategory.SCHEMA,
]

const matchesSearch = (name: string, search: string): boolean =>
    name.toLowerCase().includes(search.trim().toLowerCase())

const sortByName = (items: FileSystemImport[]): FileSystemImport[] =>
    [...items].sort((a, b) => appsItemName(a).localeCompare(appsItemName(b), undefined, { sensitivity: 'accent' }))

const withHrefAndFlagsOn = (
    items: FileSystemImport[],
    featureFlags: Record<string, boolean | string>
): FileSystemImport[] => items.filter((item) => !!item.href && (!item.flag || !!featureFlags[item.flag]))

export const navAppsTabLogic = kea<navAppsTabLogicType>([
    path(['layout', 'panel-layout', 'ai-first', 'tabs', 'navAppsTabLogic']),
    connect(() => ({
        // Mounts only; values are read via direct selector references below, because
        // kea-typegen degrades connected-value types when the source logic's generated
        // types are unavailable
        logic: [featureFlagLogic, projectTreeDataLogic],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    reducers({
        search: ['', { setSearch: (_, { search }) => search }],
    }),
    selectors({
        groupedItems: [
            (s) => [featureFlagLogic.selectors.featureFlags, projectTreeDataLogic.selectors.groupItems, s.search],
            (
                featureFlags: Record<string, boolean | string>,
                groupItems: FileSystemImport[],
                search: string
            ): AppsItemGroup[] => {
                const allItems = [
                    ...withHrefAndFlagsOn(getDefaultTreeProducts(), featureFlags),
                    {
                        path: 'Activity',
                        type: 'activity',
                        iconType: 'activity',
                        category: ProductItemCategory.TOOLS,
                        href: urls.activity(ActivityTab.ExploreEvents),
                    } as FileSystemImport,
                    ...withHrefAndFlagsOn(getDefaultTreeDataAndPeople(), featureFlags),
                    ...withHrefAndFlagsOn(groupItems, featureFlags),
                ]
                const filtered = search
                    ? allItems.filter((item) => matchesSearch(appsItemName(item), search))
                    : allItems
                const byCategory = new Map<string, FileSystemImport[]>()
                for (const item of filtered) {
                    const label = (item.category as string) || 'Other'
                    byCategory.set(label, [...(byCategory.get(label) ?? []), item])
                }
                const orderOf = (label: string): number => {
                    const index = APPS_CATEGORY_ORDER.indexOf(label)
                    return index === -1 ? APPS_CATEGORY_ORDER.length : index
                }
                return [...byCategory.entries()]
                    .sort(([a], [b]) => orderOf(a) - orderOf(b) || a.localeCompare(b))
                    .map(([label, items]) => ({ label, items: sortByName(items) }))
            },
        ],
        starredItems: [
            (s) => [projectTreeDataLogic.selectors.shortcutData, s.search],
            (shortcutData: FileSystemEntry[], search: string): FileSystemEntry[] => {
                const nonFolders = shortcutData.filter((entry) => entry.type !== 'folder')
                return search ? nonFolders.filter((entry) => matchesSearch(appsItemName(entry), search)) : nonFolders
            },
        ],
    }),
])
