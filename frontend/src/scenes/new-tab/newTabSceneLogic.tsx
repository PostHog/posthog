import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import { IconApps, IconArrowRight, IconDatabase, IconHogQL, IconPerson, IconSparkles, IconToggle } from '@posthog/icons'

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

import { SearchInputCommand } from './components/SearchInput'
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
    | 'askAI'

export type NEW_TAB_COMMANDS =
    | 'all'
    | 'create-new'
    | 'apps'
    | 'data-management'
    | 'recents'
    | 'persons'
    | 'eventDefinitions'
    | 'propertyDefinitions'
    | 'askAI'

export const NEW_TAB_COMMANDS_ITEMS: SearchInputCommand<NEW_TAB_COMMANDS>[] = [
    { value: 'all', displayName: 'All' },
    { value: 'create-new', displayName: 'Create new' },
    { value: 'apps', displayName: 'Apps' },
    { value: 'data-management', displayName: 'Data management' },
    { value: 'recents', displayName: 'Recents files' },
    { value: 'persons', displayName: 'Persons' },
    { value: 'eventDefinitions', displayName: 'Events' },
    { value: 'propertyDefinitions', displayName: 'Properties' },
    { value: 'askAI', displayName: 'Posthog AI' },
]

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

const PAGINATION_LIMIT = 10

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
        setNewTabSceneDataInclude: (include: NEW_TAB_COMMANDS[]) => ({ include }),
        toggleNewTabSceneDataInclude: (item: NEW_TAB_COMMANDS) => ({ item }),
        triggerSearchForIncludedItems: true,
        refreshDataAfterToggle: true,
        showMoreInSection: (section: string) => ({ section }),
        resetSectionLimits: true,
        askAI: (searchTerm: string) => ({ searchTerm }),
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

                    const response = await api.persons.list({ search: searchTerm.trim(), limit: 5 })
                    breakpoint()

                    return response.results
                },
                loadInitialPersons: async (_, breakpoint) => {
                    const response = await api.persons.list({ limit: 5 })
                    breakpoint()

                    return response.results
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
                        limit: 5,
                    })
                    breakpoint()

                    return response.results ?? []
                },
                loadInitialEventDefinitions: async (_, breakpoint) => {
                    const response = await api.eventDefinitions.list({
                        limit: 5,
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
                        limit: 5,
                    })
                    breakpoint()

                    return response.results ?? []
                },
                loadInitialPropertyDefinitions: async (_, breakpoint) => {
                    const response = await api.propertyDefinitions.list({
                        limit: 5,
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
            ['all'] as NEW_TAB_COMMANDS[],
            {
                setNewTabSceneDataInclude: (_, { include }) => include,
                toggleNewTabSceneDataInclude: (state, { item }) => {
                    if (item === 'all') {
                        // Handle "all" toggle
                        if (state.includes('all')) {
                            return state.filter((i) => i !== 'all')
                        }
                        return ['all']
                    }
                    // Handle individual command toggle
                    if (state.includes(item)) {
                        // Remove the item
                        const newState = state.filter((i) => i !== item)
                        // If no items left, default back to "all"
                        return newState.length === 0 ? ['all'] : newState
                    }
                    // Add the item and remove "all" if it was selected
                    const newState = state.filter((i) => i !== 'all')
                    return [...newState, item]
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
        sectionItemLimits: [
            {} as Record<string, number>,
            {
                showMoreInSection: (state, { section }) => ({
                    ...state,
                    [section]: Infinity,
                }),
                resetSectionLimits: () => ({}),
                setSearch: () => ({}),
                toggleNewTabSceneDataInclude: () => ({}),
            },
        ],
    }),
    selectors(({ actions }) => ({
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
                    categories.push({
                        key: 'askAI',
                        label: 'Ask Posthog AI',
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
        aiSearchItems: [
            (s) => [s.search],
            (search: string): NewTabTreeDataItem[] => {
                const searchTerm = search.trim()
                const items: NewTabTreeDataItem[] = []

                const askDirectQuestionToAiItem: NewTabTreeDataItem = {
                    id: 'ask-ai',
                    name: searchTerm ? `Ask: ${searchTerm}` : 'Ask Posthog AI anything...',
                    category: 'askAI',
                    href: urls.max(undefined, searchTerm),
                    icon: <IconSparkles />,
                    record: {
                        type: 'ai',
                        path: searchTerm ? `Ask Posthog AI: ${searchTerm}` : 'Ask Posthog AI',
                        href: '#',
                        searchTerm: searchTerm || '',
                        onClick: () => actions.askAI(searchTerm),
                    },
                }
                const openAiInTabItem: NewTabTreeDataItem = {
                    id: 'open-ai',
                    name: 'Open',
                    category: 'askAI',
                    href: urls.max(undefined, undefined),
                    icon: <IconArrowRight />,
                    record: {
                        type: 'ai',
                        path: 'Open',
                        href: '#',
                        searchTerm: '',
                    },
                }
                // Only if there is a search term, add the ask direct question to ai item
                if (searchTerm) {
                    items.push(askDirectQuestionToAiItem)
                }
                items.push(openAiInTabItem)
                return items
            },
        ],
        getSectionItemLimit: [
            (s) => [s.sectionItemLimits],
            (sectionItemLimits: Record<string, number>) => (section: string) => sectionItemLimits[section] || 5,
        ],
        itemsGrid: [
            (s) => [s.featureFlags, s.projectTreeSearchItems, s.aiSearchItems],
            (
                featureFlags: any,
                projectTreeSearchItems: NewTabTreeDataItem[],
                aiSearchItems: NewTabTreeDataItem[]
            ): NewTabTreeDataItem[] => {
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

                const newTabSceneData = featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

                const allItems: NewTabTreeDataItem[] = [
                    ...(newTabSceneData ? aiSearchItems : []),
                    {
                        id: 'new-sql-query',
                        name: 'New SQL query',
                        category: 'create-new',
                        icon: <IconDatabase />,
                        href: '/sql',
                        record: { type: 'query', path: 'New SQL query' },
                    },
                    ...newInsightItems,
                    ...newOtherItems,
                    ...products,
                    ...data,
                    ...newDataItems,
                    ...projectTreeSearchItems,
                    {
                        id: 'new-hog-program',
                        name: 'New Hog program',
                        category: 'create-new',
                        icon: <IconHogQL />,
                        href: '/debug/hog',
                        record: { type: 'hog', path: 'New Hog program' },
                    },
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
                s.newTabSceneDataInclude,
                s.personSearchItems,
                s.eventDefinitionSearchItems,
                s.propertyDefinitionSearchItems,
                s.aiSearchItems,
                s.featureFlags,
                s.getSectionItemLimit,
            ],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                newTabSceneDataInclude: NEW_TAB_COMMANDS[],
                personSearchItems: NewTabTreeDataItem[],
                eventDefinitionSearchItems: NewTabTreeDataItem[],
                propertyDefinitionSearchItems: NewTabTreeDataItem[],
                aiSearchItems: NewTabTreeDataItem[],
                featureFlags: any,
                getSectionItemLimit: (section: string) => number
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

                // Check if "all" is selected
                const showAll = newTabSceneDataInclude.includes('all')

                // Group items by category and filter based on what's selected
                const grouped: Record<string, NewTabTreeDataItem[]> = {}

                // Add persons section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('persons')) {
                    const limit = getSectionItemLimit('persons')
                    grouped['persons'] = personSearchItems.slice(0, limit)
                }
                // Add event definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('eventDefinitions')) {
                    const limit = getSectionItemLimit('eventDefinitions')
                    grouped['eventDefinitions'] = eventDefinitionSearchItems.slice(0, limit)
                }

                // Add property definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('propertyDefinitions')) {
                    const limit = getSectionItemLimit('propertyDefinitions')
                    grouped['propertyDefinitions'] = propertyDefinitionSearchItems.slice(0, limit)
                }

                // Add each category only if it's selected or if "all" is selected
                if (showAll || newTabSceneDataInclude.includes('create-new')) {
                    const limit = getSectionItemLimit('create-new')
                    grouped['create-new'] = filterBySearch(
                        itemsGrid.filter((item) => item.category === 'create-new')
                    ).slice(0, limit)
                }

                if (showAll || newTabSceneDataInclude.includes('apps')) {
                    const limit = getSectionItemLimit('apps')
                    grouped['apps'] = filterBySearch(itemsGrid.filter((item) => item.category === 'apps')).slice(
                        0,
                        limit
                    )
                }

                if (showAll || newTabSceneDataInclude.includes('data-management')) {
                    const limit = getSectionItemLimit('data-management')
                    grouped['data-management'] = filterBySearch(
                        itemsGrid.filter((item) => item.category === 'data-management')
                    ).slice(0, limit)
                }

                if (showAll || newTabSceneDataInclude.includes('recents')) {
                    const limit = getSectionItemLimit('recents')
                    grouped['recents'] = filterBySearch(itemsGrid.filter((item) => item.category === 'recents')).slice(
                        0,
                        limit
                    )
                }

                // Add AI section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('askAI')) {
                    const limit = getSectionItemLimit('askAI')
                    grouped['askAI'] = aiSearchItems.slice(0, limit)
                }

                return grouped
            },
        ],
        newTabSceneDataGroupedItemsFullData: [
            (s) => [
                s.itemsGrid,
                s.search,
                s.newTabSceneDataInclude,
                s.personSearchItems,
                s.eventDefinitionSearchItems,
                s.propertyDefinitionSearchItems,
                s.aiSearchItems,
                s.featureFlags,
            ],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                newTabSceneDataInclude: NEW_TAB_COMMANDS[],
                personSearchItems: NewTabTreeDataItem[],
                eventDefinitionSearchItems: NewTabTreeDataItem[],
                propertyDefinitionSearchItems: NewTabTreeDataItem[],
                aiSearchItems: NewTabTreeDataItem[],
                featureFlags: any
            ): Record<string, number> => {
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

                // Check if "all" is selected
                const showAll = newTabSceneDataInclude.includes('all')

                // Track full counts for each section
                const fullCounts: Record<string, number> = {}

                // Add persons section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('persons')) {
                    fullCounts['persons'] = personSearchItems.length
                }
                // Add event definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('eventDefinitions')) {
                    fullCounts['eventDefinitions'] = eventDefinitionSearchItems.length
                }

                // Add property definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('propertyDefinitions')) {
                    fullCounts['propertyDefinitions'] = propertyDefinitionSearchItems.length
                }

                // Add each category only if it's selected or if "all" is selected
                if (showAll || newTabSceneDataInclude.includes('create-new')) {
                    fullCounts['create-new'] = filterBySearch(
                        itemsGrid.filter((item) => item.category === 'create-new')
                    ).length
                }

                if (showAll || newTabSceneDataInclude.includes('apps')) {
                    fullCounts['apps'] = filterBySearch(itemsGrid.filter((item) => item.category === 'apps')).length
                }

                if (showAll || newTabSceneDataInclude.includes('data-management')) {
                    fullCounts['data-management'] = filterBySearch(
                        itemsGrid.filter((item) => item.category === 'data-management')
                    ).length
                }

                if (showAll || newTabSceneDataInclude.includes('recents')) {
                    fullCounts['recents'] = filterBySearch(
                        itemsGrid.filter((item) => item.category === 'recents')
                    ).length
                }

                // Add AI section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('askAI')) {
                    fullCounts['askAI'] = aiSearchItems.length
                }

                return fullCounts
            },
        ],
        allCategories: [
            (s) => [s.featureFlags, s.groupedFilteredItems, s.newTabSceneDataGroupedItems, s.newTabSceneDataInclude],
            (
                featureFlags: any,
                groupedFilteredItems: Record<string, NewTabTreeDataItem[]>,
                newTabSceneDataGroupedItems: Record<string, NewTabTreeDataItem[]>,
                newTabSceneDataInclude: NEW_TAB_COMMANDS[]
            ): Array<[string, NewTabTreeDataItem[]]> => {
                const newTabSceneData = featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

                if (!newTabSceneData) {
                    return Object.entries(groupedFilteredItems)
                }

                const orderedSections: string[] = []
                const showAll = newTabSceneDataInclude.includes('all')

                // Add sections in a useful order
                const mainSections = ['create-new', 'apps', 'data-management', 'recents']
                mainSections.forEach((section) => {
                    if (showAll || newTabSceneDataInclude.includes(section as NEW_TAB_COMMANDS)) {
                        orderedSections.push(section)
                    }
                })
                if (showAll || newTabSceneDataInclude.includes('persons')) {
                    orderedSections.push('persons')
                }
                if (showAll || newTabSceneDataInclude.includes('eventDefinitions')) {
                    orderedSections.push('eventDefinitions')
                }
                if (showAll || newTabSceneDataInclude.includes('propertyDefinitions')) {
                    orderedSections.push('propertyDefinitions')
                }
                if (showAll || newTabSceneDataInclude.includes('askAI')) {
                    orderedSections.push('askAI')
                }

                return orderedSections
                    .map(
                        (section) =>
                            [section, newTabSceneDataGroupedItems[section] || []] as [string, NewTabTreeDataItem[]]
                    )
                    .filter(([, items]) => {
                        // If include is NOT 'all', keep all enabled sections visible (even when empty)
                        if (!showAll) {
                            return true
                        }

                        // If include is 'all', hide empty sections
                        return items.length > 0
                    })
            },
        ],
        firstCategoryWithResults: [
            (s) => [s.allCategories],
            (allCategories: Array<[string, NewTabTreeDataItem[]]>): string | null => {
                for (const [category, items] of allCategories) {
                    // Check if any category has items
                    if (items.length > 0) {
                        return category
                    }
                }

                return null
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
    })),
    listeners(({ actions, values }) => ({
        triggerSearchForIncludedItems: () => {
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            if (newTabSceneData) {
                const searchTerm = values.search.trim()

                // Expand 'all' to include all data types
                const itemsToProcess = values.newTabSceneDataInclude.includes('all')
                    ? ['persons', 'eventDefinitions', 'propertyDefinitions', 'askAI']
                    : values.newTabSceneDataInclude

                itemsToProcess.forEach((item) => {
                    if (searchTerm !== '') {
                        if (item === 'persons') {
                            actions.debouncedPersonSearch(searchTerm)
                        } else if (item === 'eventDefinitions') {
                            actions.debouncedEventDefinitionSearch(searchTerm)
                        } else if (item === 'propertyDefinitions') {
                            actions.debouncedPropertyDefinitionSearch(searchTerm)
                        }
                    } else {
                        // Load initial data when no search term
                        if (item === 'persons') {
                            actions.loadInitialPersons({})
                        } else if (item === 'eventDefinitions') {
                            actions.loadInitialEventDefinitions({})
                        } else if (item === 'propertyDefinitions') {
                            actions.loadInitialPropertyDefinitions({})
                        }
                    }
                })
            }
        },
        onSubmit: () => {
            if (values.selectedItem) {
                if (values.selectedItem.category === 'askAI' && values.selectedItem.record?.searchTerm) {
                    actions.askAI(values.selectedItem.record.searchTerm)
                } else if (values.selectedItem.href) {
                    router.actions.push(values.selectedItem.href)
                }
            }
        },
        setSearch: () => {
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            actions.loadRecents()

            // For newTabSceneData mode, trigger searches for included items
            if (newTabSceneData) {
                const searchTerm = values.search.trim()

                // Expand 'all' to include all data types
                const itemsToProcess = values.newTabSceneDataInclude.includes('all')
                    ? ['persons', 'eventDefinitions', 'propertyDefinitions', 'askAI']
                    : values.newTabSceneDataInclude

                itemsToProcess.forEach((item) => {
                    if (searchTerm !== '') {
                        if (item === 'persons') {
                            actions.debouncedPersonSearch(searchTerm)
                        } else if (item === 'eventDefinitions') {
                            actions.debouncedEventDefinitionSearch(searchTerm)
                        } else if (item === 'propertyDefinitions') {
                            actions.debouncedPropertyDefinitionSearch(searchTerm)
                        }
                    } else {
                        // Load initial data when no search term
                        if (item === 'persons') {
                            actions.loadInitialPersons({})
                        } else if (item === 'eventDefinitions') {
                            actions.loadInitialEventDefinitions({})
                        } else if (item === 'propertyDefinitions') {
                            actions.loadInitialPropertyDefinitions({})
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
        setNewTabSceneDataInclude: () => {
            // Trigger data loading when the include array changes
            actions.triggerSearchForIncludedItems()
        },
        refreshDataAfterToggle: () => {
            // This action triggers after toggle to refresh data
            actions.triggerSearchForIncludedItems()
        },
        debouncedPersonSearch: async ({ searchTerm }, breakpoint) => {
            // Debounce for 300ms
            await breakpoint(300)

            try {
                // Manually trigger the search and handle the result
                const response = await api.persons.list({ search: searchTerm.trim(), limit: 5 })
                breakpoint()

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
                    limit: 5,
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
                    limit: 5,
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
                category:
                    !values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.selectedCategory !== 'all'
                        ? values.selectedCategory
                        : undefined,
                include:
                    values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.newTabSceneDataInclude.length > 0
                        ? values.newTabSceneDataInclude.join(',')
                        : undefined,
            },
        ],
        setSelectedCategory: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category:
                    !values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.selectedCategory !== 'all'
                        ? values.selectedCategory
                        : undefined,
                include:
                    values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.newTabSceneDataInclude.length > 0
                        ? values.newTabSceneDataInclude.join(',')
                        : undefined,
            },
        ],
        setNewTabSceneDataInclude: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category:
                    !values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.selectedCategory !== 'all'
                        ? values.selectedCategory
                        : undefined,
                include:
                    values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.newTabSceneDataInclude.length > 0
                        ? values.newTabSceneDataInclude.join(',')
                        : undefined,
            },
        ],
        toggleNewTabSceneDataInclude: () => [
            router.values.location.pathname,
            {
                search: values.search || undefined,
                category:
                    !values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.selectedCategory !== 'all'
                        ? values.selectedCategory
                        : undefined,
                include:
                    values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE] && values.newTabSceneDataInclude.length > 0
                        ? values.newTabSceneDataInclude.join(',')
                        : undefined,
            },
        ],
    })),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.newTab()]: (_, searchParams) => {
            const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]

            // Update search if URL search param differs from current state
            if (searchParams.search && searchParams.search !== values.search) {
                actions.setSearch(String(searchParams.search))

                // Trigger searches for already included items when search term changes
                if (newTabSceneData && values.newTabSceneDataInclude.length > 0) {
                    const searchTerm = String(searchParams.search).trim()
                    if (searchTerm !== '') {
                        // Expand 'all' to include all data types
                        const itemsToProcess = values.newTabSceneDataInclude.includes('all')
                            ? ['persons', 'eventDefinitions', 'propertyDefinitions']
                            : values.newTabSceneDataInclude

                        itemsToProcess.forEach((item) => {
                            if (item === 'persons') {
                                actions.debouncedPersonSearch(searchTerm)
                            } else if (item === 'eventDefinitions') {
                                actions.debouncedEventDefinitionSearch(searchTerm)
                            } else if (item === 'propertyDefinitions') {
                                actions.debouncedPropertyDefinitionSearch(searchTerm)
                            }
                        })
                    }
                }
            }

            // Update category if URL category param differs from current state
            if (!newTabSceneData && searchParams.category && searchParams.category !== values.selectedCategory) {
                actions.setSelectedCategory(searchParams.category)
            }

            // Update include array if URL param differs from current state
            const includeFromUrl: NEW_TAB_COMMANDS[] = searchParams.include
                ? (searchParams.include as string)
                      .split(',')
                      .filter((item): item is NEW_TAB_COMMANDS =>
                          [
                              'all',
                              'create-new',
                              'apps',
                              'data-management',
                              'recents',
                              'persons',
                              'eventDefinitions',
                              'propertyDefinitions',
                              'askAI',
                          ].includes(item)
                      )
                : []

            const currentIncludeString = values.newTabSceneDataInclude.slice().sort().join(',')
            const urlIncludeString = includeFromUrl.slice().sort().join(',')

            if (newTabSceneData && currentIncludeString !== urlIncludeString) {
                actions.setNewTabSceneDataInclude(includeFromUrl)

                // Load data for included items
                const searchTerm = searchParams.search ? String(searchParams.search).trim() : ''

                // Expand 'all' to include all data types
                const itemsToProcess = includeFromUrl.includes('all')
                    ? ['persons', 'eventDefinitions', 'propertyDefinitions', 'askAI']
                    : includeFromUrl

                itemsToProcess.forEach((item) => {
                    if (searchTerm !== '') {
                        // If there's a search term, trigger search for data items only
                        if (item === 'persons') {
                            actions.debouncedPersonSearch(searchTerm)
                        } else if (item === 'eventDefinitions') {
                            actions.debouncedEventDefinitionSearch(searchTerm)
                        } else if (item === 'propertyDefinitions') {
                            actions.debouncedPropertyDefinitionSearch(searchTerm)
                        }
                        // For non-data items (create-new, apps, etc.), no special search needed as they're handled by itemsGrid
                    } else {
                        // Load initial data when no search term for data items only
                        if (item === 'persons') {
                            actions.loadInitialPersons({})
                        } else if (item === 'eventDefinitions') {
                            actions.loadInitialEventDefinitions({})
                        } else if (item === 'propertyDefinitions') {
                            actions.loadInitialPropertyDefinitions({})
                        }
                    }
                })
            }

            // Reset search, category, and include array to defaults if no URL params
            if (!searchParams.search && values.search) {
                actions.setSearch('')
            }
            if (!newTabSceneData && !searchParams.category && values.selectedCategory !== 'all') {
                actions.setSelectedCategory('all')
            }
            if (
                (!searchParams.include && values.newTabSceneDataInclude.length !== 1) ||
                (!searchParams.include && !values.newTabSceneDataInclude.includes('all'))
            ) {
                actions.setNewTabSceneDataInclude(['all'])
            }
        },
    })),
    afterMount(({ actions, values }) => {
        actions.loadRecents()

        // Load initial data for data sections when "all" is selected by default
        const newTabSceneData = values.featureFlags[FEATURE_FLAGS.DATA_IN_NEW_TAB_SCENE]
        if (newTabSceneData && values.newTabSceneDataInclude.includes('all')) {
            actions.loadInitialPersons({})
            actions.loadInitialEventDefinitions({})
            actions.loadInitialPropertyDefinitions({})
        }
    }),
])
