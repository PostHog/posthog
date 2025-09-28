import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { actionToUrl, router, urlToAction } from 'kea-router'

import { IconDatabase, IconHogQL } from '@posthog/icons'

import { featureFlagLogic } from 'lib/logic/featureFlagLogic'

import { PROJECT_TREE_KEY } from '~/layout/panel-layout/ProjectTree/ProjectTree'
import {
    ProductIconWrapper,
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreePersons,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import { projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export type NEW_TAB_CATEGORY_ITEMS = 'all' | 'create-new' | 'apps' | 'data-management' | 'project-items'
export interface ItemsGridItem {
    category: NEW_TAB_CATEGORY_ITEMS
    types: { name: string; icon?: JSX.Element; href?: string; flag?: string }[]
}

export interface ItemsGridItemSingle {
    category: NEW_TAB_CATEGORY_ITEMS
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
        values: [featureFlagLogic, ['featureFlags'], projectTreeLogic({ key: PROJECT_TREE_KEY }), ['searchResults']],
    })),
    key((props) => props.tabId || 'default'),
    actions({
        setSearch: (search: string) => ({ search }),
        selectNext: true,
        selectPrevious: true,
        onSubmit: true,
        setSelectedCategory: (category: NEW_TAB_CATEGORY_ITEMS) => ({ category }),
    }),
    reducers({
        search: [
            '',
            {
                setSearch: (_, { search }) => search,
            },
        ],
        selectedCategory: [
            'all' as NEW_TAB_CATEGORY_ITEMS,
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
            (): { key: NEW_TAB_CATEGORY_ITEMS; label: string }[] => [
                { key: 'all', label: 'All' },
                { key: 'create-new', label: 'Create new' },
                { key: 'apps', label: 'Apps' },
                { key: 'data-management', label: 'Data management' },
                { key: 'project-items', label: 'Project items' },
            ],
        ],
        isSearching: [
            (s) => [s.search, s.searchResults],
            (search: string, searchResults: any): boolean => {
                const trimmedSearch = search.trim()
                const hasSearch = trimmedSearch.length >= 2

                if (!hasSearch) {
                    return false
                }

                // We're searching if:
                // 1. There's a search term but no results yet
                // 2. The search term doesn't match what was searched for
                // 3. The results are empty but we should have results (loading)
                return (
                    hasSearch &&
                    (!searchResults.results ||
                        searchResults.searchTerm !== trimmedSearch ||
                        (searchResults.results.length === 0 && searchResults.searchTerm !== trimmedSearch))
                )
            },
        ],
        projectTreeSearchItems: [
            (s) => [s.searchResults, s.search],
            (searchResults, search): ItemsGridItem[] => {
                // Always show project items category
                const hasSearch = search.trim().length > 0
                const hasResults = searchResults.results && searchResults.results.length > 0

                if (hasSearch && hasResults) {
                    // Show actual search results
                    const searchItems = searchResults.results.map((item) => ({
                        href: item.href || '#',
                        name: item.path,
                        icon: getIconForFileSystemItem({
                            type: item.type,
                            iconType: item.type as any,
                            path: item.path,
                        }),
                    }))

                    return [
                        {
                            category: 'project-items',
                            types: searchItems,
                        },
                    ]
                }
                // Show empty category with special handling for UI
                return [
                    {
                        category: 'project-items',
                        types: [],
                    },
                ]
            },
        ],
        itemsGrid: [
            (s) => [s.featureFlags, s.projectTreeSearchItems],
            (featureFlags, projectTreeSearchItems): ItemsGridItem[] => {
                const newInsightItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Insight/'))
                    .map((fs) => ({
                        href: fs.href,
                        name: 'New ' + fs.path.substring(8),
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
                        name: 'New ' + fs.path,
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
                            { name: 'New SQL query', icon: <IconDatabase />, href: '/sql' },
                            ...newInsightItems,
                            ...newOtherItems,
                            { name: 'New Hog program', icon: <IconHogQL />, href: '/debug/hog' },
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
                    ...projectTreeSearchItems,
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
                    .filter(({ category, types }) => types.length > 0 || category === 'project-items')
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
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'new-tab', name: 'New tab', iconType: 'blank' }]],
    }),
    listeners(({ values, cache }) => ({
        onSubmit: () => {
            if (values.selectedItem?.type?.href) {
                router.actions.push(values.selectedItem.type.href)
            }
        },
        setSearch: ({ search }) => {
            const trimmedSearch = search.trim()
            const projectTreeActions = projectTreeLogic({ key: PROJECT_TREE_KEY }).actions

            // Clear any existing timeout
            if (cache.searchTimeout) {
                clearTimeout(cache.searchTimeout)
                cache.searchTimeout = null
            }

            if (trimmedSearch.length >= 2) {
                // Trigger project tree search with debounce
                cache.searchTimeout = setTimeout(() => {
                    projectTreeActions.setSearchTerm(trimmedSearch)
                    cache.searchTimeout = null
                }, 300)
            } else {
                // Immediately clear search when input is too short
                projectTreeActions.clearSearch()
            }
        },
    })),
    actionToUrl(({ values }) => ({
        setSearch: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category: values.selectedCategory !== 'all' ? values.selectedCategory : undefined,
            },
        ],
        setSelectedCategory: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category: values.selectedCategory !== 'all' ? values.selectedCategory : undefined,
            },
        ],
    })),
    urlToAction(({ actions, values }) => ({
        '*': (_, searchParams) => {
            if (searchParams.search && searchParams.search !== values.search) {
                actions.setSearch(searchParams.search)
            }
            if (searchParams.category && searchParams.category !== values.selectedCategory) {
                actions.setSelectedCategory(searchParams.category)
            }
            // Set defaults from URL if no params
            if (!searchParams.search && values.search) {
                actions.setSearch('')
            }
            if (!searchParams.category && values.selectedCategory !== 'all') {
                actions.setSelectedCategory('all')
            }
        },
    })),
])
