import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconDatabase, IconHogQL } from '@posthog/icons'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { urls } from 'scenes/urls'

import {
    ProductIconWrapper,
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreePersons,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import { SearchResults } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { TreeDataItem } from '~/lib/lemon-ui/LemonTree/LemonTree'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { Breadcrumb } from '~/types'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export type NEW_TAB_CATEGORY_ITEMS = 'all' | 'create-new' | 'apps' | 'data-management' | 'recents'

export interface NewTabTreeDataItem extends TreeDataItem {
    category: NEW_TAB_CATEGORY_ITEMS
    href?: string
    flag?: string
}

const PAGINATION_LIMIT = 20

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
        setSelectedCategory: (category: NEW_TAB_CATEGORY_ITEMS) => ({ category }),
        loadRecents: true,
    }),
    loaders(({ values }) => ({
        recents: [
            (() => {
                if ('sessionStorage' in window) {
                    try {
                        const value = window.sessionStorage.getItem(`newTab-recentItems-${getCurrentTeamId()}`)
                        const recents = value ? JSON.parse(value) : null
                        if (recents) {
                            return recents
                        }
                    } catch {
                        // do nothing
                    }
                }
                return { results: [], hasMore: false, startTime: null, endTime: null }
            }) as any as SearchResults,
            {
                loadRecents: async (_, breakpoint) => {
                    if (values.recentsLoading) {
                        await breakpoint(250)
                    }
                    const searchTerm = values.search.trim()
                    const response = await api.fileSystem.list({
                        search: '"name:' + searchTerm + '"',
                        limit: PAGINATION_LIMIT + 1,
                        orderBy: '-created_at',
                        notType: 'folder',
                    })
                    breakpoint()
                    const recents = {
                        searchTerm,
                        results: response.results.slice(0, PAGINATION_LIMIT),
                        hasMore: response.results.length > PAGINATION_LIMIT,
                        lastCount: Math.min(response.results.length, PAGINATION_LIMIT),
                    }
                    if ('sessionStorage' in window && searchTerm === '') {
                        try {
                            window.sessionStorage.setItem(
                                `newTab-recentItems-${getCurrentTeamId()}`,
                                JSON.stringify(recents)
                            )
                        } catch {
                            // do nothing
                        }
                    }
                    return recents
                },
            },
        ],
    })),
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
                { key: 'recents', label: 'Recents' },
            ],
        ],
        isSearching: [(s) => [s.recentsLoading], (recentsLoading): boolean => recentsLoading],
        projectTreeSearchItems: [
            (s) => [s.recents],
            (recents): NewTabTreeDataItem[] => {
                return recents.results.map((item) => {
                    const name = splitPath(item.path).pop()
                    return {
                        id: item.path,
                        name: name || item.path,
                        category: 'recents',
                        href: item.href || '#',
                        icon: getIconForFileSystemItem({
                            type: item.type,
                            iconType: item.type as any,
                            path: item.path,
                        }),
                        record: item,
                    }
                })
            },
        ],
        itemsGrid: [
            (s) => [s.featureFlags, s.projectTreeSearchItems],
            (featureFlags, projectTreeSearchItems): NewTabTreeDataItem[] => {
                const newInsightItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Insight/'))
                    .map((fs, index) => ({
                        id: `new-insight-${index}`,
                        name: 'New ' + fs.path.substring(8),
                        category: 'create-new' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const newDataItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Data/'))
                    .map((fs, index) => ({
                        id: `new-data-${index}`,
                        name: 'Data ' + fs.path.substring(5).toLowerCase(),
                        category: 'data-management' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const newOtherItems = getDefaultTreeNew()
                    .filter(({ path }) => !path.startsWith('Insight/') && !path.startsWith('Data/'))
                    .map((fs, index) => ({
                        id: `new-other-${index}`,
                        name: 'New ' + fs.path,
                        category: 'create-new' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const products = [...getDefaultTreeProducts(), ...getDefaultTreePersons()]
                    .map((fs, index) => ({
                        id: `product-${index}`,
                        name: fs.path,
                        category: 'apps' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                    .toSorted((a, b) => a.name.localeCompare(b.name))

                const data = getDefaultTreeData()
                    .map((fs, index) => ({
                        id: `data-${index}`,
                        name: fs.path,
                        category: 'data-management' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const allItems: NewTabTreeDataItem[] = [
                    {
                        id: 'new-sql-query',
                        name: 'New SQL query',
                        category: 'create-new',
                        icon: <IconDatabase />,
                        href: '/sql',
                        record: { type: 'query', path: 'New SQL query' },
                    },
                    {
                        id: 'new-hog-program',
                        name: 'New Hog program',
                        category: 'create-new',
                        icon: <IconHogQL />,
                        href: '/debug/hog',
                        record: { type: 'hog', path: 'New Hog program' },
                    },
                    ...newInsightItems,
                    ...newOtherItems,
                    ...products,
                    ...data,
                    ...newDataItems,
                    ...projectTreeSearchItems,
                ]
                return allItems
            },
        ],
        filteredItemsGrid: [
            (s) => [s.itemsGrid, s.search, s.selectedCategory],
            (itemsGrid, search, selectedCategory): NewTabTreeDataItem[] => {
                let filtered = itemsGrid

                // Filter by selected category
                if (selectedCategory !== 'all') {
                    filtered = filtered.filter((item) => item.category === selectedCategory)
                }

                // Filter by search
                if (!String(search).trim()) {
                    return filtered
                }
                const lowerSearchChunks = search
                    .toLowerCase()
                    .split(' ')
                    .map((s) => s.trim())
                    .filter((s) => s)
                return filtered.filter(
                    (item) =>
                        lowerSearchChunks.filter(
                            (lowerSearch) => !`${item.category} ${item.name}`.toLowerCase().includes(lowerSearch)
                        ).length === 0
                )
            },
        ],
        filteredItemsList: [
            (s) => [s.filteredItemsGrid],
            (filteredItemsGrid): NewTabTreeDataItem[] => filteredItemsGrid,
        ],
        groupedFilteredItems: [
            (s) => [s.filteredItemsGrid],
            (filteredItemsGrid: NewTabTreeDataItem[]): Record<string, NewTabTreeDataItem[]> => {
                return filteredItemsGrid.reduce(
                    (acc: Record<string, NewTabTreeDataItem[]>, item: NewTabTreeDataItem) => {
                        if (!acc[item.category]) {
                            acc[item.category] = []
                        }
                        acc[item.category].push(item)
                        return acc
                    },
                    {} as Record<string, NewTabTreeDataItem[]>
                )
            },
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
            (selectedIndex, filteredItemsList): NewTabTreeDataItem | null =>
                selectedIndex !== null && selectedIndex < filteredItemsList.length
                    ? filteredItemsList[selectedIndex]
                    : null,
        ],
        breadcrumbs: [() => [], (): Breadcrumb[] => [{ key: 'new-tab', name: 'New tab', iconType: 'blank' }]],
    }),
    listeners(({ actions, values }) => ({
        onSubmit: () => {
            if (values.selectedItem?.href) {
                router.actions.push(values.selectedItem.href)
            }
        },
        setSearch: () => {
            actions.loadRecents()
        },
    })),
    tabAwareActionToUrl(({ values }) => ({
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
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.newTab()]: (_, searchParams) => {
            if (searchParams.search && searchParams.search !== values.search) {
                actions.setSearch(String(searchParams.search))
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
    afterMount(({ actions }) => {
        actions.loadRecents()
    }),
])
