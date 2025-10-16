import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconApps, IconDatabase, IconHogQL, IconPerson, IconToggle } from '@posthog/icons'

import api from 'lib/api'
import { FEATURE_FLAGS } from 'lib/constants'
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
import { EventDefinition, PersonType, PropertyDefinition } from '~/types'

import type { newTabSceneLogicType } from './newTabSceneLogicType'

export type NEW_TAB_CATEGORY_ITEMS =
    | 'all'
    | 'create-new'
    | 'apps'
    | 'data-management'
    | 'recents'
    | 'persons'
    | 'eventDefinitions'
    | 'propertyDefinitions'

export type NEW_TAB_INCLUDE_ITEM = 'persons' | 'eventDefinitions' | 'propertyDefinitions'

export interface NewTabTreeDataItem extends TreeDataItem {
    category: NEW_TAB_CATEGORY_ITEMS
    href?: string
    flag?: string
}

export interface NewTabCategoryItem {
    key: NEW_TAB_CATEGORY_ITEMS
    label: string
    description?: string
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
        debouncedPersonSearch: (searchTerm: string) => ({ searchTerm }),
        debouncedEventDefinitionSearch: (searchTerm: string) => ({ searchTerm }),
        debouncedPropertyDefinitionSearch: (searchTerm: string) => ({ searchTerm }),
        setNewTabSceneDataInclude: (include: NEW_TAB_INCLUDE_ITEM[]) => ({ include }),
        toggleNewTabSceneDataInclude: (item: NEW_TAB_INCLUDE_ITEM) => ({ item }),
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
                    if (searchTerm.trim() === '') {
                        return []
                    }

                    const url = api.persons.determineListUrl({
                        search: searchTerm.trim(),
                        limit: PAGINATION_LIMIT,
                    })
                    const response = await api.get(url)
                    breakpoint()

                    return response.results
                },
                loadMorePersonSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    if (searchTerm.trim() === '') {
                        return values.personSearchResults
                    }

                    const currentResults = values.personSearchResults

                    const url = api.persons.determineListUrl({
                        search: searchTerm.trim(),
                        limit: PAGINATION_LIMIT,
                        offset: currentResults.length,
                    })
                    const response = await api.get(url)
                    breakpoint()

                    return [...currentResults, ...response.results]
                },
            },
        ],
        eventDefinitionSearchResults: [
            [] as EventDefinition[],
            {
                loadEventDefinitionSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()
                    await breakpoint(200)

                    const response = await api.eventDefinitions.list({
                        search: trimmed || undefined,
                        limit: PAGINATION_LIMIT,
                    })
                    breakpoint()

                    return response.results ?? []
                },
            },
        ],
        propertyDefinitionSearchResults: [
            [] as PropertyDefinition[],
            {
                loadPropertyDefinitionSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()
                    await breakpoint(200)

                    const response = await api.propertyDefinitions.list({
                        search: trimmed || undefined,
                        limit: PAGINATION_LIMIT,
                    })
                    breakpoint()

                    return response.results ?? []
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
        newTabSceneDataInclude: [
            [] as NEW_TAB_INCLUDE_ITEM[],
            {
                setNewTabSceneDataInclude: (_, { include }) => include,
                toggleNewTabSceneDataInclude: (state, { item }) => {
                    if (state.includes(item)) {
                        return state.filter((i) => i !== item)
                    }
                    return [...state, item]
                },
            },
        ],
        personSearchPending: [
            false,
            {
                debouncedPersonSearch: () => true,
                loadPersonSearchResults: () => false,
                loadPersonSearchResultsSuccess: () => false,
                loadPersonSearchResultsFailure: () => false,
            },
        ],
        eventDefinitionSearchPending: [
            false,
            {
                debouncedEventDefinitionSearch: () => true,
                loadEventDefinitionSearchResults: () => false,
                loadEventDefinitionSearchResultsSuccess: () => false,
                loadEventDefinitionSearchResultsFailure: () => false,
            },
        ],
        propertyDefinitionSearchPending: [
            false,
            {
                debouncedPropertyDefinitionSearch: () => true,
                loadPropertyDefinitionSearchResults: () => false,
                loadPropertyDefinitionSearchResultsSuccess: () => false,
                loadPropertyDefinitionSearchResultsFailure: () => false,
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
        newTabSceneDataIncludePersons: [
            (s) => [s.newTabSceneDataInclude],
            (include): boolean => include.includes('persons'),
        ],
        newTabSceneDataIncludeEventDefinitions: [
            (s) => [s.newTabSceneDataInclude],
            (include): boolean => include.includes('eventDefinitions'),
        ],
        newTabSceneDataIncludePropertyDefinitions: [
            (s) => [s.newTabSceneDataInclude],
            (include): boolean => include.includes('propertyDefinitions'),
        ],
        categories: [
            (s) => [s.featureFlags],
            (featureFlags): NewTabCategoryItem[] => {
                const categories: NewTabCategoryItem[] = [
                    { key: 'all', label: 'All' },
                    {
                        key: 'create-new',
                        label: 'Create new',
                    },
                    { key: 'apps', label: 'Apps' },
                    {
                        key: 'data-management',
                        label: 'Data management',
                    },
                    { key: 'recents', label: 'Recents' },
                ]
                if (featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]) {
                    categories.push({
                        key: 'persons',
                        label: 'Persons',
                    })
                    categories.push({
                        key: 'eventDefinitions',
                        label: 'Events',
                    })
                    categories.push({
                        key: 'propertyDefinitions',
                        label: 'Properties',
                    })
                }
                return categories
            },
        ],
        isSearching: [
            (s) => [
                s.recentsLoading,
                s.personSearchResultsLoading,
                s.personSearchPending,
                s.eventDefinitionSearchResultsLoading,
                s.eventDefinitionSearchPending,
                s.propertyDefinitionSearchResultsLoading,
                s.propertyDefinitionSearchPending,
                s.search,
            ],
            (
                recentsLoading: boolean,
                personSearchResultsLoading: boolean,
                personSearchPending: boolean,
                eventDefinitionSearchResultsLoading: boolean,
                eventDefinitionSearchPending: boolean,
                propertyDefinitionSearchResultsLoading: boolean,
                propertyDefinitionSearchPending: boolean,
                search: string
            ): boolean =>
                (recentsLoading ||
                    personSearchResultsLoading ||
                    personSearchPending ||
                    eventDefinitionSearchResultsLoading ||
                    eventDefinitionSearchPending ||
                    propertyDefinitionSearchResultsLoading ||
                    propertyDefinitionSearchPending) &&
                search.trim() !== '',
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
        eventDefinitionSearchItems: [
            (s) => [s.eventDefinitionSearchResults],
            (eventDefinitionSearchResults): NewTabTreeDataItem[] => {
                const items = eventDefinitionSearchResults.map((eventDef) => {
                    const item = {
                        id: `event-definition-${eventDef.id}`,
                        name: eventDef.name,
                        category: 'eventDefinitions' as NEW_TAB_CATEGORY_ITEMS,
                        href: `events://${eventDef.name}`,
                        icon: <IconToggle />,
                        record: {
                            type: 'event-definition',
                            path: `Event: ${eventDef.name}`,
                            href: `events://${eventDef.name}`,
                        },
                    }
                    return item
                })
                return items
            },
        ],
        propertyDefinitionSearchItems: [
            (s) => [s.propertyDefinitionSearchResults],
            (propertyDefinitionSearchResults): NewTabTreeDataItem[] => {
                const items = propertyDefinitionSearchResults.map((propDef) => {
                    const item = {
                        id: `property-definition-${propDef.id}`,
                        name: propDef.name,
                        category: 'propertyDefinitions' as NEW_TAB_CATEGORY_ITEMS,
                        href: `properties://${propDef.name}`,
                        icon: <IconApps />,
                        record: {
                            type: 'property-definition',
                            path: `Property: ${propDef.name}`,
                            href: `properties://${propDef.name}`,
                        },
                    }
                    return item
                })
                return items
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
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                selectedCategory: NEW_TAB_CATEGORY_ITEMS
            ): NewTabTreeDataItem[] => {
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
        newTabSceneDataGroupedItems: [
            (s) => [
                s.itemsGrid,
                s.search,
                s.newTabSceneDataIncludePersons,
                s.personSearchItems,
                s.newTabSceneDataIncludeEventDefinitions,
                s.eventDefinitionSearchItems,
                s.newTabSceneDataIncludePropertyDefinitions,
                s.propertyDefinitionSearchItems,
                s.featureFlags,
            ],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                includePersons: boolean,
                personSearchItems: NewTabTreeDataItem[],
                includeEventDefinitions: boolean,
                eventDefinitionSearchItems: NewTabTreeDataItem[],
                includePropertyDefinitions: boolean,
                propertyDefinitionSearchItems: NewTabTreeDataItem[],
                featureFlags
            ): Record<string, NewTabTreeDataItem[]> => {
                const newTabSceneData = featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]
                if (!newTabSceneData) {
                    return {}
                }

                // Filter all items by search term
                const searchLower = search.toLowerCase().trim()
                const filterBySearch = (items: NewTabTreeDataItem[]): NewTabTreeDataItem[] => {
                    if (!searchLower) {
                        return items
                    }
                    const searchChunks = searchLower.split(' ').filter((s) => s)
                    return items.filter((item) =>
                        searchChunks.every(
                            (chunk) =>
                                item.name.toLowerCase().includes(chunk) || item.category.toLowerCase().includes(chunk)
                        )
                    )
                }

                // Group items by category and filter
                const grouped: Record<string, NewTabTreeDataItem[]> = {
                    'create-new': filterBySearch(itemsGrid.filter((item) => item.category === 'create-new')),
                    apps: filterBySearch(itemsGrid.filter((item) => item.category === 'apps')),
                    'data-management': filterBySearch(itemsGrid.filter((item) => item.category === 'data-management')),
                    recents: filterBySearch(itemsGrid.filter((item) => item.category === 'recents')),
                }

                // Add persons section if filter is enabled
                if (includePersons) {
                    // Only show person results if there's a search term, otherwise empty array
                    grouped['persons'] = search.trim() ? personSearchItems : []
                }

                // Add event definitions section if filter is enabled
                if (includeEventDefinitions) {
                    grouped['eventDefinitions'] = search.trim() ? eventDefinitionSearchItems : []
                }

                // Add property definitions section if filter is enabled
                if (includePropertyDefinitions) {
                    grouped['propertyDefinitions'] = search.trim() ? propertyDefinitionSearchItems : []
                }

                return grouped
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
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            actions.loadRecents()

            // For newTabSceneData mode, trigger searches for included items
            if (newTabSceneData) {
                const searchTerm = values.search.trim()

                values.newTabSceneDataInclude.forEach((item) => {
                    if (searchTerm !== '') {
                        if (item === 'persons') {
                            actions.debouncedPersonSearch(searchTerm)
                        } else if (item === 'eventDefinitions') {
                            actions.debouncedEventDefinitionSearch(searchTerm)
                        } else if (item === 'propertyDefinitions') {
                            actions.debouncedPropertyDefinitionSearch(searchTerm)
                        }
                    } else {
                        // Clear results when search is empty
                        if (item === 'persons') {
                            actions.loadPersonSearchResultsSuccess([])
                        } else if (item === 'eventDefinitions') {
                            actions.loadEventDefinitionSearchResultsSuccess([])
                        } else if (item === 'propertyDefinitions') {
                            actions.loadPropertyDefinitionSearchResultsSuccess([])
                        }
                    }
                })
            }
        },
        toggleNewTabSceneDataInclude: ({ item }) => {
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            if (newTabSceneData) {
                const willBeIncluded = !values.newTabSceneDataInclude.includes(item)

                if (willBeIncluded) {
                    // When enabling an item, switch to its category
                    actions.setSelectedCategory(item as NEW_TAB_CATEGORY_ITEMS)

                    // If there's a search term, trigger the appropriate search
                    if (values.search.trim() !== '') {
                        if (item === 'persons') {
                            actions.debouncedPersonSearch(values.search.trim())
                        } else if (item === 'eventDefinitions') {
                            actions.debouncedEventDefinitionSearch(values.search.trim())
                        } else if (item === 'propertyDefinitions') {
                            actions.debouncedPropertyDefinitionSearch(values.search.trim())
                        }
                    }
                } else {
                    // When disabling an item, clear its search results and go to 'all'
                    actions.setSelectedCategory('all')

                    if (item === 'persons') {
                        actions.loadPersonSearchResultsSuccess([])
                    } else if (item === 'eventDefinitions') {
                        actions.loadEventDefinitionSearchResultsSuccess([])
                    } else if (item === 'propertyDefinitions') {
                        actions.loadPropertyDefinitionSearchResultsSuccess([])
                    }
                }
            }
        },
        debouncedPersonSearch: async ({ searchTerm }, breakpoint) => {
            // Debounce for 300ms
            await breakpoint(300)

            try {
                // Manually trigger the search and handle the result
                const url = api.persons.determineListUrl({
                    search: searchTerm.trim(),
                    limit: PAGINATION_LIMIT,
                })
                const response = await api.get(url)

                // Manually set the results instead of relying on the loader
                actions.loadPersonSearchResultsSuccess(response.results)
            } catch (error) {
                console.error('Person search failed:', error)
                actions.loadPersonSearchResultsFailure(error as string)
            }
        },
        debouncedEventDefinitionSearch: async ({ searchTerm }, breakpoint) => {
            await breakpoint(300)

            try {
                const response = await api.eventDefinitions.list({
                    search: searchTerm.trim(),
                    limit: PAGINATION_LIMIT,
                })

                actions.loadEventDefinitionSearchResultsSuccess(response.results ?? [])
            } catch (error) {
                console.error('Event definition search failed:', error)
                actions.loadEventDefinitionSearchResultsFailure(error as string)
            }
        },
        debouncedPropertyDefinitionSearch: async ({ searchTerm }, breakpoint) => {
            await breakpoint(300)

            try {
                const response = await api.propertyDefinitions.list({
                    search: searchTerm.trim(),
                    limit: PAGINATION_LIMIT,
                })

                actions.loadPropertyDefinitionSearchResultsSuccess(response.results ?? [])
            } catch (error) {
                console.error('Property definition search failed:', error)
                actions.loadPropertyDefinitionSearchResultsFailure(error as string)
            }
        },
    })),
    tabAwareActionToUrl(({ values }) => ({
        setSearch: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category: values.selectedCategory !== 'all' ? values.selectedCategory : undefined,
                include: values.newTabSceneDataInclude.length > 0 ? values.newTabSceneDataInclude.join(',') : undefined,
            },
        ],
        setSelectedCategory: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category: values.selectedCategory !== 'all' ? values.selectedCategory : undefined,
                include: values.newTabSceneDataInclude.length > 0 ? values.newTabSceneDataInclude.join(',') : undefined,
            },
        ],
        setNewTabSceneDataInclude: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category: values.selectedCategory !== 'all' ? values.selectedCategory : undefined,
                include: values.newTabSceneDataInclude.length > 0 ? values.newTabSceneDataInclude.join(',') : undefined,
            },
        ],
        toggleNewTabSceneDataInclude: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category: values.selectedCategory !== 'all' ? values.selectedCategory : undefined,
                include: values.newTabSceneDataInclude.length > 0 ? values.newTabSceneDataInclude.join(',') : undefined,
            },
        ],
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.newTab()]: (_, searchParams) => {
            // Update search if URL search param differs from current state
            if (searchParams.search && searchParams.search !== values.search) {
                actions.setSearch(String(searchParams.search))
            }

            // Update category if URL category param differs from current state
            if (searchParams.category && searchParams.category !== values.selectedCategory) {
                actions.setSelectedCategory(searchParams.category)
            }

            // Update include array if URL param differs from current state
            const includeFromUrl: NEW_TAB_INCLUDE_ITEM[] = searchParams.include
                ? (searchParams.include as string)
                      .split(',')
                      .filter((item): item is NEW_TAB_INCLUDE_ITEM =>
                          ['persons', 'eventDefinitions', 'propertyDefinitions'].includes(item)
                      )
                : []

            const currentIncludeString = values.newTabSceneDataInclude.slice().sort().join(',')
            const urlIncludeString = includeFromUrl.slice().sort().join(',')

            if (currentIncludeString !== urlIncludeString) {
                actions.setNewTabSceneDataInclude(includeFromUrl)
            }

            // Reset search, category, and include array to defaults if no URL params
            if (!searchParams.search && values.search) {
                actions.setSearch('')
            }
            if (!searchParams.category && values.selectedCategory !== 'all') {
                actions.setSelectedCategory('all')
            }
            if (!searchParams.include && values.newTabSceneDataInclude.length > 0) {
                actions.setNewTabSceneDataInclude([])
            }
        },
    })),
    afterMount(({ actions }) => {
        actions.loadRecents()
    }),
])
