import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { router } from 'kea-router'

import { IconDatabase, IconHogQL } from '@posthog/icons'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import {
    ProductIconWrapper,
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreePersons,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export interface ItemsGridItem {
    category: string
    types: { name: string; icon?: JSX.Element; href?: string; flag?: string }[]
}

export interface ItemsGridItemSingle {
    category: string
    type: { name: string; icon?: JSX.Element; href?: string }
}

function getIconForFileSystemItem(fs: FileSystemImport): JSX.Element {
    // If the item has a direct icon property, use it with color wrapper
    if ('icon' in fs && fs.icon) {
        return (
            <ProductIconWrapper type={fs.type} colorOverride={fs.iconColor}>
                {fs.icon}
            </ProductIconWrapper>
        )
    }

    // Fall back to iconForType for iconType or type
    return iconForType('iconType' in fs ? fs.iconType : (fs.type as FileSystemIconType), fs.iconColor)
}

export const newTabSceneLogic = kea<newTabSceneLogicType>([
    path(['scenes', 'new-tab', 'newTabSceneLogic']),
    props({} as { tabId?: string }),
    connect(() => ({
        values: [featureFlagLogic, ['featureFlags']],
    })),
    key((props) => props.tabId || 'default'),
    actions({
        setSearch: (search: string) => ({ search }),
        selectNext: true,
        selectPrevious: true,
        onSubmit: true,
        setSelectedCategory: (category: string) => ({ category }),
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
        selectedCategory: [
            'all' as string,
            {
                setSelectedCategory: (_, { category }) => category,
            },
        ],
        rawSelectedIndex: [
            0,
            {
                selectNext: (state) => state + 1,
                selectPrevious: (state) => state - 1,
                setSearch: () => 0,
                setSelectedCategory: () => 0,
            },
        ],
    }),
    selectors({
        categories: [
            () => [],
            (): { key: string; label: string }[] => [
                { key: 'all', label: 'All' },
                { key: 'create-new', label: 'Create new' },
                { key: 'apps', label: 'Apps' },
                { key: 'data-management', label: 'Data management' },
            ],
        ],
        itemsGrid: [
            (s) => [s.featureFlags],
            (featureFlags): ItemsGridItem[] => {
                const newInsightItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Insight/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'new ' + fs.path.substring(8),
                        icon: getIconForFileSystemItem(fs),
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                const newDataItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Data/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'Data ' + fs.path.substring(5).toLowerCase(),
                        icon: getIconForFileSystemItem(fs),
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                const newOtherItems = getDefaultTreeNew()
                    .filter(({ path }) => !path.startsWith('Insight/') && !path.startsWith('Data/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'new ' + fs.path,
                        icon: getIconForFileSystemItem(fs),
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const products = [...getDefaultTreeProducts(), ...getDefaultTreePersons()]
                    .map((fs) => ({
                        href: fs.href,
                        name: fs.path,
                        icon: getIconForFileSystemItem(fs),
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                    .toSorted((a, b) => a.name.localeCompare(b.name))

                const data = getDefaultTreeData()
                    .map((fs) => ({
                        href: fs.href,
                        name: fs.path,
                        icon: getIconForFileSystemItem(fs),
                        flag: fs.flag,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const queryTree: ItemsGridItem[] = [
                    {
                        category: 'create-new',
                        types: [
                            { name: 'new SQL query', icon: <IconDatabase />, href: '/sql' },
                            ...newInsightItems,
                            ...newOtherItems,
                            { name: 'new Hog program', icon: <IconHogQL />, href: '/debug/hog' },
                        ],
                    },
                    {
                        category: 'apps',
                        types: [...products],
                    },
                    {
                        category: 'data-management',
                        types: [...data, ...newDataItems],
                    },
                ]
                return queryTree
            },
        ],
        filteredItemsGrid: [
            (s) => [s.itemsGrid, s.search, s.selectedCategory],
            (itemsGrid, search, selectedCategory): ItemsGridItem[] => {
                let filtered = itemsGrid

                // Filter by selected category
                if (selectedCategory !== 'all') {
                    filtered = filtered.filter(({ category }) => category === selectedCategory)
                }

                // Filter by search
                if (!search.trim()) {
                    return filtered
                }
                const lowerSearchChunks = search
                    .toLowerCase()
                    .split(' ')
                    .map((s) => s.trim())
                    .filter((s) => s)
                return filtered
                    .map(({ category, types }) => ({
                        category,
                        types: types.filter(
                            (t) =>
                                lowerSearchChunks.filter(
                                    (lowerSearch) => !`${category} ${t.name}`.toLowerCase().includes(lowerSearch)
                                ).length === 0
                        ),
                    }))
                    .filter(({ types }) => types.length > 0)
            },
        ],
        filteredItemsList: [
            (s) => [s.filteredItemsGrid],
            (filteredItemsGrid): ItemsGridItemSingle[] =>
                filteredItemsGrid.flatMap(({ category, types }) =>
                    types.map((type) => ({
                        category,
                        type,
                    }))
                ),
        ],
        selectedIndex: [
            (s) => [s.rawSelectedIndex, s.filteredItemsList],
            (rawSelectedIndex, filteredItemsList): number | null => {
                if (filteredItemsList.length === 0) {
                    return null
                }
                return (
                    ((rawSelectedIndex % filteredItemsList.length) + filteredItemsList.length) %
                    filteredItemsList.length
                )
            },
        ],
        selectedItem: [
            (s) => [s.selectedIndex, s.filteredItemsList],
            (selectedIndex, filteredItemsList) =>
                selectedIndex !== null && selectedIndex < filteredItemsList.length
                    ? filteredItemsList[selectedIndex]
                    : null,
        ],
    }),
    listeners(({ values }) => ({
        onSubmit: () => {
            if (values.selectedItem?.type?.href) {
                router.actions.push(values.selectedItem.type.href)
            }
        },
    })),
])
