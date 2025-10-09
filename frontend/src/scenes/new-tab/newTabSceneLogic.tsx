import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconDatabase, IconHogQL, IconPerson } from '@posthog/icons'

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
import { PersonType } from '~/types'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export type NEW_TAB_CATEGORY_ITEMS = 'all' | 'create-new' | 'apps' | 'data-management' | 'recents' | 'persons'

export interface NewTabTreeDataItem extends TreeDataItem {
    category: NEW_TAB_CATEGORY_ITEMS
    href?: string
    flag?: string
}

export type SpecialSearchMode = 'person' | null

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
        debouncedPersonSearch: (searchTerm: string) => ({ searchTerm }),
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
        personSearchResults: [
            [] as PersonType[],
            {
                loadPersonSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    if (!searchTerm.trim()) {
                        return []
                    }

                    const response = await api.persons.list({ search: searchTerm.trim() })
                    breakpoint()

                    return response.results
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
            (): { key: NEW_TAB_CATEGORY_ITEMS; label: string; description?: string }[] => [
                { key: 'all', label: 'All', description: 'All items in PostHog' },
                {
                    key: 'create-new',
                    label: 'Create new',
                    description: 'Create new insights, queries, experiments, etc.',
                },
                { key: 'apps', label: 'Apps', description: "All of PostHog's apps, tools, and features" },
                {
                    key: 'data-management',
                    label: 'Data management',
                    description: 'Manage your data sources and destinations',
                },
                { key: 'recents', label: 'Recents', description: 'Project-based recently accessed items' },
                { key: 'persons', label: 'Persons', description: 'Search persons by ID, email, or properties' },
            ],
        ],
        specialSearchMode: [
            (s) => [s.search, s.selectedCategory],
            (search: string, selectedCategory: NEW_TAB_CATEGORY_ITEMS): SpecialSearchMode => {
                if (search.startsWith('/person') || selectedCategory === 'persons') {
                    return 'person'
                }
                return null
            },
        ],
        isSearching: [
            (s) => [s.recentsLoading, s.personSearchResultsLoading],
            (recentsLoading: boolean, personSearchResultsLoading: boolean): boolean =>
                recentsLoading || personSearchResultsLoading,
        ],
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
        personSearchItems: [
            (s) => [s.personSearchResults],
            (personSearchResults): NewTabTreeDataItem[] => {
                const items = personSearchResults.map((person) => {
                    const personId = person.distinct_ids?.[0] || person.uuid || 'unknown'
                    const displayName = person.properties?.email || personId
                    const item = {
                        id: `person-${person.uuid}`,
                        name: `${displayName}`,
                        category: 'persons' as NEW_TAB_CATEGORY_ITEMS,
                        href: urls.personByUUID(person.uuid || ''),
                        icon: <IconPerson />,
                        record: {
                            type: 'person',
                            path: `Person: ${displayName}`,
                            href: urls.personByUUID(person.uuid || ''),
                        },
                    }

                    return item
                })

                return items
            },
        ],
        itemsGrid: [
            (s) => [s.featureFlags, s.projectTreeSearchItems, s.personSearchItems, s.specialSearchMode],
            (featureFlags, projectTreeSearchItems, personSearchItems, specialSearchMode): NewTabTreeDataItem[] => {
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

                // If in person search mode, ensure persons category always appears
                if (specialSearchMode === 'person') {
                    // Always include at least an empty persons category to prevent layout shift
                    if (personSearchItems.length === 0) {
                        return [
                            {
                                id: 'persons-placeholder',
                                name: '',
                                category: 'persons' as NEW_TAB_CATEGORY_ITEMS,
                                href: '',
                                icon: null,
                                record: { type: 'placeholder', path: '' },
                            },
                        ]
                    }
                    return personSearchItems
                }

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
            (s) => [s.itemsGrid, s.search, s.selectedCategory, s.specialSearchMode],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                selectedCategory: NEW_TAB_CATEGORY_ITEMS,
                specialSearchMode: SpecialSearchMode
            ): NewTabTreeDataItem[] => {
                let filtered = itemsGrid

                // Filter by selected category
                if (selectedCategory !== 'all') {
                    filtered = filtered.filter((item) => item.category === selectedCategory)
                }

                // For special search modes (like person search), skip the normal search filtering
                if (specialSearchMode === 'person') {
                    return filtered
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
            (s) => [s.rawSelectedIndex, s.filteredItemsGrid],
            (rawSelectedIndex, filteredItemsGrid): number | null => {
                if (filteredItemsGrid.length === 0) {
                    return null
                }
                return (
                    ((rawSelectedIndex % filteredItemsGrid.length) + filteredItemsGrid.length) %
                    filteredItemsGrid.length
                )
            },
        ],
        selectedItem: [
            (s) => [s.selectedIndex, s.filteredItemsGrid],
            (selectedIndex, filteredItemsGrid): NewTabTreeDataItem | null =>
                selectedIndex !== null && selectedIndex < filteredItemsGrid.length
                    ? filteredItemsGrid[selectedIndex]
                    : null,
        ],
    }),
    listeners(({ actions, values }) => ({
        onSubmit: () => {
            if (values.selectedItem?.href) {
                router.actions.push(values.selectedItem.href)
            }
        },
        setSearch: () => {
            // Clear previous person search results when search changes
            actions.loadPersonSearchResultsSuccess([])

            actions.loadRecents()

            // If search starts with /person or /persons, debounce the person search
            if (values.search.startsWith('/person')) {
                const searchTerm = values.search.replace(/^\/persons?\s*/, '').trim()
                if (searchTerm) {
                    // Debounce person search to avoid hitting server on every keystroke
                    actions.debouncedPersonSearch(searchTerm)
                } else {
                    // Clear results if search term is empty but still in person search mode
                    actions.loadPersonSearchResultsSuccess([])
                }
            }

            // If in persons mode and search doesn't start with /person, debounce person search results
            if (values.selectedCategory === 'persons' && !values.search.startsWith('/person') && values.search.trim()) {
                actions.debouncedPersonSearch(values.search.trim())
            }
        },
        debouncedPersonSearch: async ({ searchTerm }, breakpoint) => {
            // Debounce for 300ms
            await breakpoint(300)
            actions.loadPersonSearchResults({ searchTerm })
        },
        setSelectedCategory: ({ category }) => {
            // When switching to persons tab, auto-add /persons prefix if search is empty
            if (category === 'persons' && !values.search) {
                actions.setSearch('/persons ')
            }

            // When switching to persons tab with existing search that doesn't start with /person, trigger person search
            if (category === 'persons' && values.search && !values.search.startsWith('/person')) {
                actions.debouncedPersonSearch(values.search.trim())
            }
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
