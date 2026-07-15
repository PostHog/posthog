import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'
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
        appsItems: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags: Record<string, boolean | string>): FileSystemImport[] =>
                sortByName([
                    ...withHrefAndFlagsOn(getDefaultTreeProducts(), featureFlags),
                    {
                        path: 'Activity',
                        type: 'activity',
                        iconType: 'activity',
                        href: urls.activity(ActivityTab.ExploreEvents),
                    },
                ]),
        ],
        dataItems: [
            () => [featureFlagLogic.selectors.featureFlags],
            (featureFlags: Record<string, boolean | string>): FileSystemImport[] =>
                sortByName(withHrefAndFlagsOn(getDefaultTreeDataAndPeople(), featureFlags)),
        ],
        filteredAppsItems: [
            (s) => [s.appsItems, s.search],
            (appsItems: FileSystemImport[], search: string): FileSystemImport[] =>
                search ? appsItems.filter((item) => matchesSearch(appsItemName(item), search)) : appsItems,
        ],
        filteredDataItems: [
            (s) => [s.dataItems, s.search],
            (dataItems: FileSystemImport[], search: string): FileSystemImport[] =>
                search ? dataItems.filter((item) => matchesSearch(appsItemName(item), search)) : dataItems,
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
