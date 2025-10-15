import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconDatabase, IconHogQL, IconPerson } from '@posthog/icons'

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
import { projectTreeDataLogic } from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
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
    protocol?: string | null
}

export interface NewTabCategoryItem {
    key: NEW_TAB_CATEGORY_ITEMS
    label: string
    description?: string
}

export interface NewTabDestinationOption {
    value: string
    label: string
    description?: string
}

export type SpecialSearchMode = 'persons' | null

const PAGINATION_LIMIT = 20

const DESTINATION_ALIAS_MAP: Record<string, string> = {
    'products://': 'apps://',
}

const CATEGORY_TO_PROTOCOL_MAP: Record<string, string> = {
    'create-new': 'new://',
    apps: 'apps://',
    'data-management': 'data://',
    recents: 'project://',
    persons: 'persons://',
}

const BASE_DESTINATION_LABELS: Record<string, { label: string; description?: string }> = {
    'project://': { label: 'Project' },
    'apps://': { label: 'Apps' },
    'data://': { label: 'Data' },
    'events://': { label: 'Events' },
    'properties://': { label: 'Properties' },
    'persons://': { label: 'Persons' },
    'shortcuts://': { label: 'Shortcuts' },
    'new://': { label: 'Create new' },
    'ask://': { label: 'Ask Max', description: 'Send your query to Max' },
}

const ALWAYS_INCLUDED_DESTINATIONS = new Set(['events://', 'properties://'])

const DEFAULT_DESTINATION_ORDER = [
    'project://',
    'apps://',
    'data://',
    'events://',
    'properties://',
    'persons://',
    'shortcuts://',
    'new://',
]

const normalizeDestination = (value?: string | null): string | null => {
    if (!value) {
        return null
    }
    const normalized = value.toLowerCase()
    return DESTINATION_ALIAS_MAP[normalized] ?? normalized
}

const protocolFromCategory = (category?: string | null): string | null => {
    if (!category) {
        return null
    }
    if (category.includes('://')) {
        return normalizeDestination(category)
    }
    const mapped = CATEGORY_TO_PROTOCOL_MAP[category]
    if (mapped) {
        return mapped
    }
    return null
}

const formatDestinationLabel = (value: string): string => {
    const meta = BASE_DESTINATION_LABELS[value]
    if (meta) {
        return meta.label
    }
    const cleaned = value.replace('://', '')
    return cleaned.charAt(0).toUpperCase() + cleaned.slice(1)
}

const getProtocolForDataItem = (fs: FileSystemImport): string => {
    if (fs.iconType === 'event_definition') {
        return 'events://'
    }
    if (fs.iconType === 'property_definition') {
        return 'properties://'
    }
    return 'data://'
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
        values: [featureFlagLogic, ['featureFlags'], projectTreeDataLogic, ['getStaticTreeItems']],
    })),
    key((props) => props.tabId || 'default'),
    actions({
        setSearch: (search: string) => ({ search }),
        selectNext: true,
        selectPrevious: true,
        onSubmit: true,
        setSelectedCategory: (category: NEW_TAB_CATEGORY_ITEMS) => ({ category }),
        setSelectedDestinations: (destinations: string[]) => ({ destinations }),
        loadRecents: true,
        debouncedPersonSearch: (searchTerm: string) => ({ searchTerm }),
        setPersonSearchPagination: (pagination: { count: number; hasMore: boolean; limit: number }) => ({ pagination }),
        setNewTabSceneDataIncludePersons: (includePersons: boolean) => ({ includePersons }),
    }),
    loaders(({ actions, values }) => ({
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
                    const limit = 20
                    const url = api.persons.determineListUrl({ search: searchTerm.trim() }) + `&limit=${limit}`
                    const response = await api.get(url)
                    breakpoint()

                    // Store pagination info immediately
                    setTimeout(() => {
                        actions.setPersonSearchPagination({
                            count: response.count,
                            hasMore: Boolean(response.next),
                            limit,
                        })
                    }, 0)

                    return response.results
                },
                loadMorePersonSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    if (!searchTerm.trim()) {
                        return values.personSearchResults
                    }

                    const currentResults = values.personSearchResults
                    const offset = currentResults.length

                    const url =
                        api.persons.determineListUrl({ search: searchTerm.trim() }) + `&limit=20&offset=${offset}`
                    const response = await api.get(url)
                    breakpoint()

                    // Update pagination info
                    setTimeout(() => {
                        actions.setPersonSearchPagination({
                            count: response.count,
                            hasMore: Boolean(response.next),
                            limit: 20,
                        })
                    }, 0)

                    return [...currentResults, ...response.results]
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
        selectedDestinations: [
            [] as string[],
            {
                setSelectedDestinations: (_, { destinations }) => destinations,
            },
        ],
        personSearchPagination: [
            { count: 0, hasMore: false, limit: 20 } as { count: number; hasMore: boolean; limit: number },
            {
                setPersonSearchPagination: (_, { pagination }) => pagination,
            },
        ],
        newTabSceneDataIncludePersons: [
            false,
            {
                setNewTabSceneDataIncludePersons: (_, { includePersons }) => includePersons,
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
                }
                return categories
            },
        ],
        specialSearchMode: [
            (s) => [s.search, s.selectedCategory, s.featureFlags, s.selectedDestinations],
            (search, selectedCategory, featureFlags, selectedDestinations): SpecialSearchMode => {
                const newTabSceneDataEnabled = featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]
                if (newTabSceneDataEnabled) {
                    if (selectedDestinations.includes('persons://')) {
                        return 'persons'
                    }
                    if (search.startsWith('/person')) {
                        return 'persons'
                    }
                } else if (search.startsWith('/person') || selectedCategory === 'persons') {
                    return 'persons'
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
                    const protocol = 'project://'
                    return {
                        id: item.path,
                        name: name || item.path,
                        category: 'recents',
                        protocol,
                        href: item.href || '#',
                        icon: getIconForFileSystemItem({
                            type: item.type,
                            iconType: item.type as any,
                            path: item.path,
                        }),
                        record: {
                            ...item,
                            protocol,
                            path: item.path,
                            href: item.href || '#',
                        },
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
                    const protocol = 'persons://'
                    const item = {
                        id: `person-${person.uuid}`,
                        name: `${displayName}`,
                        category: 'persons' as NEW_TAB_CATEGORY_ITEMS,
                        href: urls.personByUUID(person.uuid || ''),
                        protocol,
                        icon: <IconPerson />,
                        record: {
                            type: 'person',
                            path: `Person: ${displayName}`,
                            href: urls.personByUUID(person.uuid || ''),
                            protocol,
                        },
                    }

                    return item
                })

                return items
            },
        ],
        itemsGrid: [
            (s) => [
                s.featureFlags,
                s.projectTreeSearchItems,
                s.personSearchItems,
                s.specialSearchMode,
                s.selectedDestinations,
            ],
            (
                featureFlags,
                projectTreeSearchItems,
                personSearchItems,
                specialSearchMode,
                selectedDestinations
            ): NewTabTreeDataItem[] => {
                const newTabSceneData = featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]
                const normalizedSelections = selectedDestinations
                    .map((destination) => normalizeDestination(destination))
                    .filter((value): value is string => !!value)

                const includePersons =
                    newTabSceneData && (normalizedSelections.includes('persons://') || specialSearchMode === 'persons')

                const newInsightItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Insight/'))
                    .map((fs, index) => {
                        const protocol = 'new://'
                        return {
                            id: `new-insight-${index}`,
                            name: 'New ' + fs.path.substring(8),
                            category: 'create-new' as NEW_TAB_CATEGORY_ITEMS,
                            href: fs.href,
                            flag: fs.flag,
                            protocol,
                            icon: getIconForFileSystemItem(fs),
                            record: { ...fs, protocol },
                        }
                    })
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const newDataItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Data/'))
                    .map((fs, index) => {
                        const protocol = 'data://'
                        return {
                            id: `new-data-${index}`,
                            name: 'Data ' + fs.path.substring(5).toLowerCase(),
                            category: 'data-management' as NEW_TAB_CATEGORY_ITEMS,
                            href: fs.href,
                            flag: fs.flag,
                            protocol,
                            icon: getIconForFileSystemItem(fs),
                            record: { ...fs, protocol },
                        }
                    })
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const newOtherItems = getDefaultTreeNew()
                    .filter(({ path }) => !path.startsWith('Insight/') && !path.startsWith('Data/'))
                    .map((fs, index) => {
                        const protocol = 'new://'
                        return {
                            id: `new-other-${index}`,
                            name: 'New ' + fs.path,
                            category: 'create-new' as NEW_TAB_CATEGORY_ITEMS,
                            href: fs.href,
                            flag: fs.flag,
                            protocol,
                            icon: getIconForFileSystemItem(fs),
                            record: { ...fs, protocol },
                        }
                    })
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const products = [...getDefaultTreeProducts(), ...getDefaultTreePersons()]
                    .map((fs, index) => {
                        const protocol = 'apps://'
                        return {
                            id: `product-${index}`,
                            name: fs.path,
                            category: 'apps' as NEW_TAB_CATEGORY_ITEMS,
                            href: fs.href,
                            flag: fs.flag,
                            protocol,
                            icon: getIconForFileSystemItem(fs),
                            record: { ...fs, protocol },
                        }
                    })
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                    .toSorted((a, b) => a.name.localeCompare(b.name))

                const data = getDefaultTreeData()
                    .map((fs, index) => {
                        const protocol = getProtocolForDataItem(fs)
                        return {
                            id: `data-${index}`,
                            name: fs.path,
                            category: 'data-management' as NEW_TAB_CATEGORY_ITEMS,
                            href: fs.href,
                            flag: fs.flag,
                            protocol,
                            icon: getIconForFileSystemItem(fs),
                            record: { ...fs, protocol },
                        }
                    })
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                if (newTabSceneData && specialSearchMode === 'persons') {
                    return personSearchItems
                }

                const baseItems: NewTabTreeDataItem[] = [
                    {
                        id: 'new-sql-query',
                        name: 'New SQL query',
                        category: 'create-new',
                        protocol: 'new://',
                        icon: <IconDatabase />,
                        href: '/sql',
                        record: { type: 'query', path: 'New SQL query', protocol: 'new://', href: '/sql' },
                    },
                    {
                        id: 'new-hog-program',
                        name: 'New Hog program',
                        category: 'create-new',
                        protocol: 'new://',
                        icon: <IconHogQL />,
                        href: '/debug/hog',
                        record: { type: 'hog', path: 'New Hog program', protocol: 'new://', href: '/debug/hog' },
                    },
                    ...newInsightItems,
                    ...newOtherItems,
                    ...products,
                    ...data,
                    ...newDataItems,
                    ...projectTreeSearchItems,
                ]

                if (includePersons && specialSearchMode !== 'persons') {
                    baseItems.push(...personSearchItems)
                }

                return baseItems
            },
        ],
        filteredItemsGrid: [
            (s) => [
                s.itemsGrid,
                s.search,
                s.selectedCategory,
                s.specialSearchMode,
                s.featureFlags,
                s.selectedDestinations,
            ],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                selectedCategory: NEW_TAB_CATEGORY_ITEMS,
                specialSearchMode: SpecialSearchMode,
                featureFlags,
                selectedDestinations: string[]
            ): NewTabTreeDataItem[] => {
                let filtered = itemsGrid

                const newTabSceneData = featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

                if (!newTabSceneData && selectedCategory !== 'all') {
                    filtered = filtered.filter((item) => item.category === selectedCategory)
                }

                if (newTabSceneData) {
                    const normalizedSelections = selectedDestinations
                        .map((destination) => normalizeDestination(destination))
                        .filter((value): value is string => !!value && value !== 'ask://')

                    if (normalizedSelections.length > 0) {
                        filtered = filtered.filter((item) => {
                            const protocol =
                                normalizeDestination(item.protocol) ||
                                protocolFromCategory(item.category) ||
                                'project://'
                            return normalizedSelections.includes(protocol)
                        })
                    }
                }

                if (specialSearchMode === 'persons') {
                    return filtered
                }

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
            (s) => [s.itemsGrid, s.featureFlags],
            (itemsGrid: NewTabTreeDataItem[], featureFlags): Record<string, NewTabTreeDataItem[]> => {
                if (!featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]) {
                    return {}
                }

                return itemsGrid.reduce(
                    (acc: Record<string, NewTabTreeDataItem[]>, item: NewTabTreeDataItem) => {
                        const protocol =
                            normalizeDestination(item.protocol) || protocolFromCategory(item.category) || 'project://'
                        if (!acc[protocol]) {
                            acc[protocol] = []
                        }
                        acc[protocol].push(item)
                        return acc
                    },
                    {} as Record<string, NewTabTreeDataItem[]>
                )
            },
        ],
        destinationOptions: [
            (s) => [s.featureFlags, s.getStaticTreeItems],
            (featureFlags, getStaticTreeItems): NewTabDestinationOption[] => {
                if (!featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]) {
                    return []
                }

                const destinations = new Set<string>()

                if (getStaticTreeItems) {
                    try {
                        const staticItems = getStaticTreeItems('', false)
                        for (const item of staticItems) {
                            const protocol = normalizeDestination(
                                (item.record?.protocol as string | undefined) ||
                                    (typeof item.id === 'string' ? item.id : undefined)
                            )
                            if (protocol) {
                                destinations.add(protocol)
                            }
                        }
                    } catch {
                        // ignore errors from fetching static items
                    }
                }

                destinations.add('project://')

                const options: NewTabDestinationOption[] = []

                for (const value of DEFAULT_DESTINATION_ORDER) {
                    if (destinations.has(value) || ALWAYS_INCLUDED_DESTINATIONS.has(value)) {
                        const meta = BASE_DESTINATION_LABELS[value]
                        options.push({
                            value,
                            label: meta ? meta.label : formatDestinationLabel(value),
                            description: meta?.description,
                        })
                    }
                }

                if (!options.some((option) => option.value === 'ask://')) {
                    const askMeta = BASE_DESTINATION_LABELS['ask://']
                    options.push({
                        value: 'ask://',
                        label: askMeta?.label ?? formatDestinationLabel('ask://'),
                        description: askMeta?.description,
                    })
                }

                return options
            },
        ],
        destinationOptionMap: [
            (s) => [s.destinationOptions],
            (destinationOptions): Record<string, NewTabDestinationOption> =>
                destinationOptions.reduce(
                    (acc, option) => {
                        acc[option.value] = option
                        return acc
                    },
                    {} as Record<string, NewTabDestinationOption>
                ),
        ],
        destinationSections: [
            (s) => [s.newTabSceneDataGroupedItems, s.destinationOptions, s.selectedDestinations, s.featureFlags],
            (
                groupedItems: Record<string, NewTabTreeDataItem[]>,
                destinationOptions: NewTabDestinationOption[],
                selectedDestinations: string[],
                featureFlags
            ): [string, NewTabTreeDataItem[]][] => {
                if (!featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]) {
                    return []
                }

                const normalizedSelection = selectedDestinations
                    .map((value) => normalizeDestination(value))
                    .filter((value): value is string => !!value && value !== 'ask://')

                const sections: [string, NewTabTreeDataItem[]][] = []
                const seen = new Set<string>()

                const orderedValues =
                    normalizedSelection.length > 0
                        ? normalizedSelection
                        : destinationOptions
                              .map((option) => normalizeDestination(option.value))
                              .filter((value): value is string => !!value && value !== 'ask://')

                for (const value of orderedValues) {
                    if (!value || seen.has(value)) {
                        continue
                    }
                    const items = groupedItems[value] || []
                    if (items.length > 0 || normalizedSelection.includes(value)) {
                        sections.push([value, items])
                        seen.add(value)
                    }
                }

                Object.entries(groupedItems).forEach(([key, items]) => {
                    const value = normalizeDestination(key)
                    if (!value || value === 'ask://') {
                        return
                    }
                    if (!seen.has(value) && items.length > 0) {
                        sections.push([value, items])
                        seen.add(value)
                    }
                })

                return sections
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

            // For newTabSceneData mode, trigger person search if includePersons is enabled and there's a search term
            if (newTabSceneData && values.newTabSceneDataIncludePersons) {
                if (values.search.trim()) {
                    actions.debouncedPersonSearch(values.search.trim())
                } else {
                    // Clear results when search is empty
                    actions.loadPersonSearchResultsSuccess([])
                }
            }
        },
        setNewTabSceneDataIncludePersons: ({ includePersons }) => {
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            if (newTabSceneData && includePersons && values.search.trim()) {
                // If enabling persons filter and there's a search term, trigger person search
                actions.debouncedPersonSearch(values.search.trim())
            } else if (newTabSceneData && !includePersons) {
                // If disabling persons filter, clear person search results
                actions.loadPersonSearchResultsSuccess([])
            }
        },
        setSelectedDestinations: ({ destinations }) => {
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            if (newTabSceneData) {
                const includePersons = destinations.includes('persons://')
                if (includePersons !== values.newTabSceneDataIncludePersons) {
                    actions.setNewTabSceneDataIncludePersons(includePersons)
                }
            }
        },
        debouncedPersonSearch: async ({ searchTerm }, breakpoint) => {
            // Debounce for 300ms
            await breakpoint(300)
            actions.loadPersonSearchResults({ searchTerm })
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
