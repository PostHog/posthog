import { actions, connect, kea, path, reducers, selectors } from 'kea'

import { FEATURE_FLAGS } from 'lib/constants'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { urls } from 'scenes/urls'

import { getDefaultTreeDataAndPeople, getDefaultTreeProducts } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { FileSystemImport } from '~/queries/schema/schema-general'
import { ActivityTab } from '~/types'

import type { appsSceneLogicType } from './appsSceneLogicType'

export function getAppItemName(item: FileSystemImport): string {
    return item.displayLabel ?? unescapePath(splitPath(item.path).pop() ?? item.path)
}

// Items from the "Project" nav section that aren't part of the products or data trees
const getExtraAppItems = (): FileSystemImport[] => [
    {
        path: 'Activity',
        iconType: 'activity',
        href: urls.activity(ActivityTab.ExploreEvents),
    },
    {
        path: 'Inbox',
        iconType: 'inbox',
        href: urls.inbox(),
        flag: FEATURE_FLAGS.PRODUCT_AUTONOMY,
        tags: ['beta'],
    },
]

export const appsSceneLogic = kea<appsSceneLogicType>([
    path(['scenes', 'apps', 'appsSceneLogic']),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setSelectedIndex: (selectedIndex: number) => ({ selectedIndex }),
    }),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        selectedIndex: [
            0,
            {
                setSelectedIndex: (_, { selectedIndex }) => selectedIndex,
                setSearchTerm: () => 0,
            },
        ],
    }),
    selectors({
        appItems: [
            (s) => [s.featureFlags],
            (featureFlags): FileSystemImport[] => {
                const seen = new Set<string>()
                return [...getDefaultTreeProducts(), ...getDefaultTreeDataAndPeople(), ...getExtraAppItems()]
                    .filter(
                        (item) => !!item.href && (!item.flag || (featureFlags as Record<string, boolean>)[item.flag])
                    )
                    .filter((item) => {
                        const name = getAppItemName(item)
                        if (seen.has(name)) {
                            return false
                        }
                        seen.add(name)
                        return true
                    })
                    .sort((a, b) =>
                        getAppItemName(a).localeCompare(getAppItemName(b), undefined, { sensitivity: 'accent' })
                    )
            },
        ],
        filteredAppItems: [
            (s) => [s.appItems, s.searchTerm],
            (appItems, searchTerm): FileSystemImport[] => {
                const tokens = searchTerm.trim().toLowerCase().split(/\s+/).filter(Boolean)
                if (tokens.length === 0) {
                    return appItems
                }
                return appItems.filter((item) => {
                    const name = getAppItemName(item).toLowerCase()
                    return tokens.every((token) => name.includes(token))
                })
            },
        ],
    }),
])
