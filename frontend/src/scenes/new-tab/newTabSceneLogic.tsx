import { actions, afterMount, connect, isBreakpoint, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import {
    IconActivity,
    IconApps,
    IconArrowRight,
    IconDatabase,
    IconGear,
    IconHogQL,
    IconPeople,
    IconPerson,
    IconSparkles,
    IconToolbar,
} from '@posthog/icons'

import api from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { tabAwareActionToUrl } from 'lib/logic/scenes/tabAwareActionToUrl'
import { tabAwareUrlToAction } from 'lib/logic/scenes/tabAwareUrlToAction'
import { capitalizeFirstLetter } from 'lib/utils'
import { getCurrentTeamId } from 'lib/utils/getAppContext'
import { groupDisplayId } from 'scenes/persons/GroupActorDisplay'
import { urls } from 'scenes/urls'

import {
    ProductIconWrapper,
    getDefaultTreeData,
    getDefaultTreeNew,
    getDefaultTreePersons,
    getDefaultTreeProducts,
    iconForType,
} from '~/layout/panel-layout/ProjectTree/defaultTree'
import {
    PAGINATION_LIMIT as PROJECT_TREE_PAGINATION_LIMIT,
    projectTreeDataLogic,
} from '~/layout/panel-layout/ProjectTree/projectTreeDataLogic'
import { SearchResults, projectTreeLogic } from '~/layout/panel-layout/ProjectTree/projectTreeLogic'
import { joinPath, sortFilesAndFolders, splitPath } from '~/layout/panel-layout/ProjectTree/utils'
import { TreeDataItem } from '~/lib/lemon-ui/LemonTree/LemonTree'
import { groupsModel } from '~/models/groupsModel'
import {
    FileSystemEntry,
    FileSystemIconType,
    FileSystemImport,
    FileSystemViewLogEntry,
} from '~/queries/schema/schema-general'
import { ActivityTab, EventDefinition, Group, GroupTypeIndex, PersonType, PropertyDefinition } from '~/types'

import { SearchInputCommand } from './components/SearchInput'
import type { newTabSceneLogicType } from './newTabSceneLogicType'

export type NEW_TAB_CATEGORY_ITEMS =
    | 'all'
    | 'project-folders'
    | 'create-new'
    | 'apps'
    | 'data-management'
    | 'recents'
    | 'persons'
    | 'groups'
    | 'eventDefinitions'
    | 'propertyDefinitions'
    | 'askAI'

export type NEW_TAB_COMMANDS =
    | 'all'
    | 'project-folders'
    | 'create-new'
    | 'apps'
    | 'data-management'
    | 'recents'
    | 'persons'
    | 'groups'
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
    { value: 'groups', displayName: 'Groups' },
    { value: 'eventDefinitions', displayName: 'Events' },
    { value: 'propertyDefinitions', displayName: 'Properties' },
    { value: 'askAI', displayName: 'Posthog AI' },
]

export interface NewTabTreeDataItem extends TreeDataItem {
    category: NEW_TAB_CATEGORY_ITEMS
    href?: string
    flag?: string
    lastViewedAt?: string | null
}

export interface CategoryWithItems {
    key: NEW_TAB_CATEGORY_ITEMS
    items: NewTabTreeDataItem[]
    isLoading: boolean
}

const INITIAL_SECTION_LIMIT = 5
const SINGLE_CATEGORY_SECTION_LIMIT = 15
const INITIAL_RECENTS_LIMIT = 5
const PAGINATION_LIMIT = 10
const GROUP_SEARCH_LIMIT = 5
const FILE_BROWSER_SEARCH_LIMIT = PROJECT_TREE_PAGINATION_LIMIT
const DEFAULT_FOLDER_SEARCH_LIMIT = 10

export type NewTabSearchDataset =
    | 'recents'
    | 'projectFolders'
    | 'persons'
    | 'groups'
    | 'eventDefinitions'
    | 'propertyDefinitions'

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

const sortByLastViewedAt = (items: NewTabTreeDataItem[]): NewTabTreeDataItem[] =>
    items
        .map((item, originalIndex) => ({ item, originalIndex }))
        .toSorted((a, b) => {
            const parseTime = (value: string | null | undefined): number => {
                if (!value) {
                    return 0
                }
                const parsed = Date.parse(value)
                return Number.isFinite(parsed) ? parsed : 0
            }
            const diff = parseTime(b.item.lastViewedAt) - parseTime(a.item.lastViewedAt)
            if (diff !== 0) {
                return diff
            }
            return a.originalIndex - b.originalIndex
        })
        .map(({ item }) => item)

function matchesRecentsSearch(entry: FileSystemEntry, searchChunks: string[]): boolean {
    if (searchChunks.length === 0) {
        return true
    }

    const name = splitPath(entry.path).pop() || entry.path
    const nameLower = name.toLowerCase()
    const typeLower = entry.type?.toLowerCase() ?? ''
    const categoryLower = 'recents'

    return searchChunks.every(
        (chunk) => nameLower.includes(chunk) || typeLower.includes(chunk) || categoryLower.includes(chunk)
    )
}

function buildFolderNameSearchQuery(search: string): string {
    const tokens = search.match(/"[^"]+"|'[^']+'|\S+/g) ?? []

    return tokens
        .map((token) => {
            const isNegated = token.startsWith('-') || token.startsWith('!')
            const prefix = isNegated ? token[0] : ''
            const remainder = isNegated ? token.slice(1) : token

            if (!remainder) {
                return token
            }

            if (remainder.includes(':')) {
                return `${prefix}${remainder}`
            }

            return `${prefix}name:${remainder}`
        })
        .join(' ')
}

function buildProjectPathUrl(path: string): string {
    const trimmed = path.replace(/^\/+/, '').replace(/\/+$/, '')
    const projectUri = trimmed ? `project://${trimmed}/` : 'project://'
    return `${urls.newTab()}?projectPath=${encodeURIComponent(projectUri)}`
}

function normalizeProjectPath(projectPath: string | null): string {
    if (!projectPath) {
        return ''
    }
    const withoutProtocol = projectPath.startsWith('project://') ? projectPath.slice('project://'.length) : projectPath
    return withoutProtocol.replace(/\/+$/, '')
}

export const newTabSceneLogic = kea<newTabSceneLogicType>([
    path(['scenes', 'new-tab', 'newTabSceneLogic']),
    props({} as { tabId?: string }),
    key((props) => props.tabId || 'default'),
    connect(({ tabId }) => ({
        values: [
            featureFlagLogic,
            ['featureFlags'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            projectTreeDataLogic,
            ['folders', 'folderStates'],
            projectTreeLogic({ key: `new-tab-${tabId}` }),
            [
                'searchResults as projectTreeSearchResults',
                'searchResultsLoading as projectTreeSearchResultsLoading',
                'searchTerm as projectTreeSearchTerm',
            ],
        ],
        actions: [
            projectTreeDataLogic,
            ['loadFolder'],
            projectTreeLogic({ key: `new-tab-${tabId}` }),
            [
                'setSearchTerm as setProjectTreeSearchTerm',
                'clearSearch as clearProjectTreeSearch',
                'loadSearchResults as loadProjectTreeSearchResults',
            ],
        ],
    })),
    actions({
        setSearch: (search: string) => ({ search }),
        selectNext: true,
        selectPrevious: true,
        onSubmit: true,
        setSelectedCategory: (category: NEW_TAB_CATEGORY_ITEMS) => ({ category }),
        loadRecents: (options?: { offset?: number }) => ({ offset: options?.offset ?? 0 }),
        loadMoreRecents: true,
        loadProjectFolderSearchResults: (searchTerm: string) => ({ searchTerm }),
        debouncedProjectFolderSearch: (searchTerm: string) => ({ searchTerm }),
        debouncedPersonSearch: (searchTerm: string) => ({ searchTerm }),
        debouncedEventDefinitionSearch: (searchTerm: string) => ({ searchTerm }),
        debouncedPropertyDefinitionSearch: (searchTerm: string) => ({ searchTerm }),
        debouncedGroupSearch: (searchTerm: string) => ({ searchTerm }),
        setProjectPath: (projectPath: string | null) => ({ projectPath }),
        loadMoreFileBrowser: true,
        setNewTabSceneDataInclude: (include: NEW_TAB_COMMANDS[]) => ({ include }),
        toggleNewTabSceneDataInclude: (item: NEW_TAB_COMMANDS) => ({ item }),
        triggerSearchForIncludedItems: true,
        refreshDataAfterToggle: true,
        showMoreInSection: (section: string) => ({ section }),
        setSectionItemLimit: (section: string, limit: number) => ({ section, limit }),
        resetSectionLimits: true,
        askAI: (searchTerm: string) => ({ searchTerm }),
        logCreateNewItem: (href: string | null | undefined) => ({ href }),
        loadInitialGroups: true,
        setFirstNoResultsSearchPrefix: (dataset: NewTabSearchDataset, prefix: string | null) => ({
            dataset,
            prefix,
        }),
    }),
    loaders(({ values, actions }) => ({
        sceneLogViews: [
            [] as FileSystemViewLogEntry[],
            {
                loadSceneLogViews: async () => {
                    return await api.fileSystemLogView.list({ type: 'scene' })
                },
            },
        ],
        newLogViews: [
            [] as FileSystemViewLogEntry[],
            {
                loadNewLogViews: async () => {
                    return await api.fileSystemLogView.list({ type: 'create-new' })
                },
            },
        ],
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
                loadRecents: async ({ offset }, breakpoint) => {
                    if (values.recentsLoading) {
                        await breakpoint(250)
                    }
                    const searchTerm = values.search.trim()
                    const noResultsPrefix = values.firstNoResultsSearchPrefixes.recents

                    const requestedOffset = offset ?? 0
                    const isAppending =
                        requestedOffset > 0 &&
                        values.recents.searchTerm === searchTerm &&
                        values.recents.results.length > 0
                    const effectiveOffset = isAppending ? requestedOffset : 0

                    if (
                        effectiveOffset === 0 &&
                        searchTerm &&
                        noResultsPrefix &&
                        searchTerm.length > noResultsPrefix.length &&
                        searchTerm.startsWith(noResultsPrefix)
                    ) {
                        return {
                            searchTerm,
                            results: [],
                            hasMore: false,
                            lastCount: 0,
                        }
                    }

                    const pageLimit = effectiveOffset === 0 ? INITIAL_RECENTS_LIMIT : PAGINATION_LIMIT

                    const response = await api.fileSystem.list({
                        search: searchTerm,
                        limit: pageLimit + 1,
                        orderBy: '-last_viewed_at',
                        notType: 'folder',
                        offset: effectiveOffset,
                    })
                    breakpoint()
                    const searchChunks = searchTerm
                        .toLowerCase()
                        .split(' ')
                        .filter((s) => s)
                    const filteredCount = searchTerm
                        ? response.results.filter((item) => matchesRecentsSearch(item, searchChunks)).length
                        : response.results.length
                    const newResults = response.results.slice(0, pageLimit)
                    const combinedResults =
                        isAppending && values.recents.searchTerm === searchTerm
                            ? [...values.recents.results, ...newResults]
                            : newResults
                    const recents = {
                        searchTerm,
                        results: combinedResults,
                        hasMore: response.results.length > pageLimit,
                        lastCount: newResults.length,
                    }
                    if (effectiveOffset === 0) {
                        if (searchTerm) {
                            actions.setFirstNoResultsSearchPrefix('recents', filteredCount === 0 ? searchTerm : null)
                        } else {
                            actions.setFirstNoResultsSearchPrefix('recents', null)
                        }
                    }
                    if ('sessionStorage' in window && searchTerm === '' && effectiveOffset === 0) {
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
        projectFolderSearchResults: [
            [] as FileSystemEntry[],
            {
                loadProjectFolderSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        actions.setFirstNoResultsSearchPrefix('projectFolders', null)
                        return []
                    }

                    const noResultsPrefix = values.firstNoResultsSearchPrefixes.projectFolders
                    if (
                        noResultsPrefix &&
                        trimmed.length > noResultsPrefix.length &&
                        trimmed.startsWith(noResultsPrefix)
                    ) {
                        return []
                    }

                    await breakpoint(250)

                    try {
                        const searchLimit = values.projectPath ? FILE_BROWSER_SEARCH_LIMIT : DEFAULT_FOLDER_SEARCH_LIMIT
                        const nameOnlySearch = buildFolderNameSearchQuery(trimmed) || `name:${trimmed}`
                        const response = await api.fileSystem.list({
                            search: nameOnlySearch,
                            limit: searchLimit,
                            type: 'folder',
                        })
                        breakpoint()

                        const results = response.results || []
                        actions.setFirstNoResultsSearchPrefix('projectFolders', results.length === 0 ? trimmed : null)
                        return results
                    } catch (error) {
                        if (!isBreakpoint(error)) {
                            console.error('Project folder search failed:', error)
                            throw error
                        }
                        return []
                    }
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

                    actions.setFirstNoResultsSearchPrefix('persons', null)

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

                    actions.setFirstNoResultsSearchPrefix('eventDefinitions', null)

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

                    actions.setFirstNoResultsSearchPrefix('propertyDefinitions', null)

                    return response.results ?? []
                },
            },
        ],
        groupSearchResults: [
            {} as Partial<Record<GroupTypeIndex, Group[]>>,
            {
                loadGroupSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        actions.setFirstNoResultsSearchPrefix('groups', null)
                        return {}
                    }

                    const noResultsPrefix = values.firstNoResultsSearchPrefixes.groups

                    if (
                        trimmed &&
                        noResultsPrefix &&
                        trimmed.length > noResultsPrefix.length &&
                        trimmed.startsWith(noResultsPrefix)
                    ) {
                        return {}
                    }

                    const groupTypesList = Array.from(values.groupTypes.values())
                    if (groupTypesList.length === 0) {
                        actions.setFirstNoResultsSearchPrefix('groups', null)
                        return {}
                    }

                    await breakpoint(200)

                    const responses = await Promise.all(
                        groupTypesList.map((groupType) =>
                            api.groups.list({
                                group_type_index: groupType.group_type_index,
                                search: trimmed,
                                limit: GROUP_SEARCH_LIMIT,
                            })
                        )
                    )

                    breakpoint()

                    const resultEntries = responses.map((response, index) => [
                        groupTypesList[index].group_type_index,
                        (response.results ?? []).slice(0, GROUP_SEARCH_LIMIT),
                    ]) as [GroupTypeIndex, Group[]][]

                    const combinedResultsCount = resultEntries.reduce(
                        (count, [, groupResults]) => count + groupResults.length,
                        0
                    )

                    if (trimmed && combinedResultsCount === 0) {
                        actions.setFirstNoResultsSearchPrefix('groups', trimmed)
                    }

                    return Object.fromEntries(resultEntries) as Record<GroupTypeIndex, Group[]>
                },
                loadInitialGroups: async (_, breakpoint) => {
                    const groupTypesList = Array.from(values.groupTypes.values())
                    if (groupTypesList.length === 0) {
                        return {}
                    }

                    await breakpoint(200)

                    const responses = await Promise.all(
                        groupTypesList.map((groupType) =>
                            api.groups.list({
                                group_type_index: groupType.group_type_index,
                                search: '',
                                limit: GROUP_SEARCH_LIMIT,
                            })
                        )
                    )

                    breakpoint()

                    actions.setFirstNoResultsSearchPrefix('groups', null)

                    return Object.fromEntries(
                        responses.map((response, index) => [
                            groupTypesList[index].group_type_index,
                            response.results.slice(0, GROUP_SEARCH_LIMIT),
                        ])
                    ) as Record<GroupTypeIndex, Group[]>
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
        groupSearchPending: [
            false,
            {
                debouncedGroupSearch: () => true,
                loadGroupSearchResults: () => false,
                loadGroupSearchResultsSuccess: () => false,
                loadGroupSearchResultsFailure: () => false,
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
                    [section]: section === 'recents' ? (state[section] ?? INITIAL_SECTION_LIMIT) : Infinity,
                }),
                setSectionItemLimit: (state, { section, limit }) => ({
                    ...state,
                    [section]: limit,
                }),
                resetSectionLimits: () => ({}),
                setSearch: () => ({}),
                toggleNewTabSceneDataInclude: () => ({}),
            },
        ],
        projectPath: [
            null as string | null,
            {
                setProjectPath: (_, { projectPath }) => projectPath,
            },
        ],
        firstNoResultsSearchPrefixes: [
            {
                recents: null,
                projectFolders: null,
                persons: null,
                groups: null,
                eventDefinitions: null,
                propertyDefinitions: null,
            } as Record<NewTabSearchDataset, string | null>,
            {
                setFirstNoResultsSearchPrefix: (state, { dataset, prefix }) => ({
                    ...state,
                    [dataset]: prefix,
                }),
                setSearch: (state, { search }) => {
                    if (search.trim() === '') {
                        return {
                            recents: null,
                            projectFolders: null,
                            persons: null,
                            groups: null,
                            eventDefinitions: null,
                            propertyDefinitions: null,
                        }
                    }
                    return state
                },
            },
        ],
    }),
    selectors(({ actions }) => ({
        sceneLogViewsByRef: [
            (s) => [s.sceneLogViews],
            (sceneLogViews): Record<string, string> => {
                return sceneLogViews.reduce(
                    (acc, { ref, viewed_at }) => {
                        const current = acc[ref]
                        if (!current || Date.parse(viewed_at) > Date.parse(current)) {
                            acc[ref] = viewed_at
                        }
                        return acc
                    },
                    {} as Record<string, string>
                )
            },
        ],
        newLogViewsByRef: [
            (s) => [s.newLogViews],
            (newLogViews): Record<string, string> => {
                return newLogViews.reduce(
                    (acc, { ref, viewed_at }) => {
                        const current = acc[ref]
                        if (!current || Date.parse(viewed_at) > Date.parse(current)) {
                            acc[ref] = viewed_at
                        }
                        return acc
                    },
                    {} as Record<string, string>
                )
            },
        ],
        isSearching: [
            (s) => [
                s.recentsLoading,
                s.projectFolderSearchResultsLoading,
                s.personSearchResultsLoading,
                s.personSearchPending,
                s.eventDefinitionSearchResultsLoading,
                s.eventDefinitionSearchPending,
                s.propertyDefinitionSearchResultsLoading,
                s.propertyDefinitionSearchPending,
                s.groupSearchResultsLoading,
                s.groupSearchPending,
                s.search,
            ],
            (
                recentsLoading: boolean,
                projectFolderSearchResultsLoading: boolean,
                personSearchResultsLoading: boolean,
                personSearchPending: boolean,
                eventDefinitionSearchResultsLoading: boolean,
                eventDefinitionSearchPending: boolean,
                propertyDefinitionSearchResultsLoading: boolean,
                propertyDefinitionSearchPending: boolean,
                groupSearchResultsLoading: boolean,
                groupSearchPending: boolean,
                search: string
            ): boolean =>
                (recentsLoading ||
                    projectFolderSearchResultsLoading ||
                    personSearchResultsLoading ||
                    personSearchPending ||
                    eventDefinitionSearchResultsLoading ||
                    eventDefinitionSearchPending ||
                    propertyDefinitionSearchResultsLoading ||
                    propertyDefinitionSearchPending ||
                    groupSearchResultsLoading ||
                    groupSearchPending) &&
                search.trim() !== '',
        ],
        categoryLoadingStates: [
            (s) => [
                s.recentsLoading,
                s.projectFolderSearchResultsLoading,
                s.personSearchResultsLoading,
                s.personSearchPending,
                s.eventDefinitionSearchResultsLoading,
                s.eventDefinitionSearchPending,
                s.propertyDefinitionSearchResultsLoading,
                s.propertyDefinitionSearchPending,
                s.groupSearchResultsLoading,
                s.groupSearchPending,
            ],
            (
                recentsLoading: boolean,
                projectFolderSearchResultsLoading: boolean,
                personSearchResultsLoading: boolean,
                personSearchPending: boolean,
                eventDefinitionSearchResultsLoading: boolean,
                eventDefinitionSearchPending: boolean,
                propertyDefinitionSearchResultsLoading: boolean,
                propertyDefinitionSearchPending: boolean,
                groupSearchResultsLoading: boolean,
                groupSearchPending: boolean
            ): Record<NEW_TAB_CATEGORY_ITEMS, boolean> => ({
                all: false,
                'project-folders': projectFolderSearchResultsLoading,
                'create-new': false,
                apps: false,
                'data-management': false,
                recents: recentsLoading,
                persons: personSearchResultsLoading || personSearchPending,
                groups: groupSearchResultsLoading || groupSearchPending,
                eventDefinitions: eventDefinitionSearchResultsLoading || eventDefinitionSearchPending,
                propertyDefinitions: propertyDefinitionSearchResultsLoading || propertyDefinitionSearchPending,
                askAI: false,
            }),
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
                        lastViewedAt: item.last_viewed_at ?? null,
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
        projectFolderSearchItems: [
            (s) => [s.projectFolderSearchResults],
            (projectFolderSearchResults): NewTabTreeDataItem[] =>
                projectFolderSearchResults.map((folder) => {
                    const path = folder.path ?? ''
                    const segments = splitPath(path)
                    const displayName = segments.length > 0 ? segments[segments.length - 1] : 'Project root'
                    const href = buildProjectPathUrl(path)
                    return {
                        id: `project-folder-${folder.id ?? (path || 'root')}`,
                        name: path || 'Project root',
                        displayName,
                        category: 'project-folders',
                        href,
                        icon: iconForType('folder' as FileSystemIconType),
                        record: {
                            ...folder,
                            type: 'folder',
                            path,
                            href,
                        },
                    }
                }),
        ],
        projectFolderItems: [
            (s) => [s.projectFolderSearchItems, s.search],
            (projectFolderSearchItems, search): NewTabTreeDataItem[] => {
                const rootHref = buildProjectPathUrl('')
                const items: NewTabTreeDataItem[] = [
                    {
                        id: 'project-folder-root',
                        name: 'Project root',
                        category: 'project-folders',
                        href: rootHref,
                        icon: iconForType('folder' as FileSystemIconType),
                        record: {
                            type: 'folder',
                            path: '',
                            href: rootHref,
                        },
                    },
                ]

                if (search.trim() !== '') {
                    items.push(...projectFolderSearchItems)
                }

                return items
            },
        ],
        projectFolderPath: [(s) => [s.projectPath], (projectPath): string => normalizeProjectPath(projectPath)],
        isFileBrowserMode: [(s) => [s.projectPath], (projectPath): boolean => projectPath !== null],
        fileBrowserParentPath: [
            (s) => [s.projectFolderPath],
            (projectFolderPath): string | null => {
                const segments = splitPath(projectFolderPath)
                if (segments.length === 0) {
                    return ''
                }
                return joinPath(segments.slice(0, -1))
            },
        ],
        fileBrowserBreadcrumbs: [
            (s) => [s.projectFolderPath],
            (projectFolderPath) => {
                const segments = splitPath(projectFolderPath)
                return segments.map((segment, index) => ({
                    label: segment,
                    path: joinPath(segments.slice(0, index + 1)),
                }))
            },
        ],
        currentFolderEntries: [
            (s) => [s.projectFolderPath, s.folders],
            (projectFolderPath, folders): FileSystemEntry[] => {
                const entries = folders[projectFolderPath] || []
                return [...entries].sort(sortFilesAndFolders)
            },
        ],
        fileBrowserFilteredEntries: [
            (s) => [
                s.currentFolderEntries,
                s.search,
                s.projectTreeSearchResults,
                s.projectTreeSearchTerm,
                s.projectFolderPath,
            ],
            (
                entries: FileSystemEntry[],
                search: string,
                projectTreeSearchResults,
                projectTreeSearchTerm,
                projectFolderPath
            ): FileSystemEntry[] => {
                const trimmed = search.trim()
                if (!trimmed) {
                    return entries
                }

                const lowerSearch = trimmed.toLowerCase()
                const chunks = lowerSearch.split(' ').filter((chunk) => chunk)
                if (chunks.length === 0) {
                    return entries
                }

                const directMatches = entries.filter((entry) => {
                    const name = splitPath(entry.path).pop()?.toLowerCase() ?? ''
                    const type = entry.type?.toLowerCase() ?? ''
                    return chunks.every((chunk) => name.includes(chunk) || type.includes(chunk))
                })

                const seenPaths = new Set(directMatches.map((entry) => entry.path))
                const descendantMatches: FileSystemEntry[] = []
                const treeSearchTermLower = (projectTreeSearchTerm ?? '').trim().toLowerCase()
                const treeResultsTermLower = projectTreeSearchResults.searchTerm.trim().toLowerCase()
                const treeSearchMatches = treeSearchTermLower === lowerSearch && treeResultsTermLower === lowerSearch

                if (treeSearchMatches) {
                    for (const entry of projectTreeSearchResults.results) {
                        if (!entry.path) {
                            continue
                        }

                        if (projectFolderPath) {
                            if (entry.path === projectFolderPath) {
                                continue
                            }
                            if (!entry.path.startsWith(`${projectFolderPath}/`)) {
                                continue
                            }
                        }

                        if (seenPaths.has(entry.path)) {
                            continue
                        }

                        const name = splitPath(entry.path).pop()?.toLowerCase() ?? ''
                        const type = entry.type?.toLowerCase() ?? ''
                        if (!chunks.every((chunk) => name.includes(chunk) || type.includes(chunk))) {
                            continue
                        }

                        seenPaths.add(entry.path)
                        descendantMatches.push(entry)
                    }
                }

                return [...directMatches, ...descendantMatches]
            },
        ],
        fileBrowserListItems: [
            (s) => [s.fileBrowserFilteredEntries],
            (entries: FileSystemEntry[]): NewTabTreeDataItem[] =>
                entries.map((entry) => {
                    const href = entry.type === 'folder' ? buildProjectPathUrl(entry.path) : entry.href || '#'
                    return {
                        id: `browser-${entry.id ?? entry.path}`,
                        name: entry.path,
                        displayName: splitPath(entry.path).pop() || entry.path,
                        category: 'project-folders',
                        href,
                        icon: getIconForFileSystemItem({
                            type: entry.type,
                            iconType: entry.type as any,
                            path: entry.path,
                        }),
                        record: entry,
                        lastViewedAt: null,
                    }
                }),
        ],
        fileBrowserFirstFolderMatch: [
            (s) => [s.fileBrowserFilteredEntries],
            (entries): FileSystemEntry | null => entries.find((entry) => entry.type === 'folder') ?? null,
        ],
        fileBrowserHasMore: [
            (s) => [s.projectFolderPath, s.folderStates, s.search, s.projectTreeSearchResults],
            (projectFolderPath, folderStates, search, projectTreeSearchResults): boolean => {
                if (search.trim()) {
                    return projectTreeSearchResults.hasMore
                }
                return folderStates[projectFolderPath] === 'has-more'
            },
        ],
        fileBrowserIsLoading: [
            (s) => [s.projectFolderPath, s.folderStates, s.search, s.projectTreeSearchResultsLoading],
            (projectFolderPath, folderStates, search, projectTreeSearchResultsLoading): boolean => {
                if (search.trim()) {
                    return projectTreeSearchResultsLoading
                }
                return folderStates[projectFolderPath] === 'loading'
            },
        ],
        personSearchItems: [
            (s) => [s.personSearchResults],
            (personSearchResults): NewTabTreeDataItem[] => {
                return personSearchResults.map((person) => {
                    const personId = person.distinct_ids?.[0] || person.uuid || 'unknown'
                    const displayName = person.properties?.email || personId
                    return {
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
                })
            },
        ],
        eventDefinitionSearchItems: [
            (s) => [s.eventDefinitionSearchResults],
            (eventDefinitionSearchResults): NewTabTreeDataItem[] => {
                return eventDefinitionSearchResults.map((eventDef) => {
                    return {
                        id: `event-definition-${eventDef.id}`,
                        name: eventDef.name,
                        category: 'eventDefinitions' as NEW_TAB_CATEGORY_ITEMS,
                        href: urls.eventDefinition(eventDef.id),
                        icon: <IconApps />,
                        record: {
                            type: 'event-definition',
                            path: `Event: ${eventDef.name}`,
                            href: urls.eventDefinition(eventDef.id),
                        },
                    }
                })
            },
        ],
        propertyDefinitionSearchItems: [
            (s) => [s.propertyDefinitionSearchResults],
            (propertyDefinitionSearchResults): NewTabTreeDataItem[] => {
                return propertyDefinitionSearchResults.map((propDef) => {
                    return {
                        id: `property-definition-${propDef.id}`,
                        name: propDef.name,
                        category: 'propertyDefinitions' as NEW_TAB_CATEGORY_ITEMS,
                        href: urls.propertyDefinition(propDef.id),
                        icon: <IconApps />,
                        record: {
                            type: 'property-definition',
                            path: `Property: ${propDef.name}`,
                            href: urls.propertyDefinition(propDef.id),
                        },
                    }
                })
            },
        ],
        groupSearchItems: [
            (s) => [s.groupSearchResults, s.aggregationLabel],
            (groupSearchResults: Record<GroupTypeIndex, Group[]>, aggregationLabel): NewTabTreeDataItem[] => {
                const items: NewTabTreeDataItem[] = []
                for (const [groupTypeIndexString, groups] of Object.entries(groupSearchResults)) {
                    const groupTypeIndex = parseInt(groupTypeIndexString, 10) as GroupTypeIndex
                    const noun = aggregationLabel(groupTypeIndex).singular
                    groups.forEach((group) => {
                        const display = groupDisplayId(group.group_key, group.group_properties || {})
                        const href = urls.group(groupTypeIndex, group.group_key)
                        items.push({
                            id: `group-${groupTypeIndex}-${group.group_key}`,
                            name: `${noun}: ${display}`,
                            displayName: display,
                            category: 'groups' as NEW_TAB_CATEGORY_ITEMS,
                            href,
                            icon: <IconPeople />,
                            record: {
                                type: 'group',
                                path: `${noun}: ${display}`,
                                href,
                                groupTypeIndex,
                                groupKey: group.group_key,
                                groupNoun: noun,
                                groupDisplayName: display,
                            },
                        })
                    })
                }

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
            (s) => [s.sectionItemLimits, s.newTabSceneDataInclude],
            (sectionItemLimits: Record<string, number>, newTabSceneDataInclude: NEW_TAB_COMMANDS[]) => {
                const singleSelectedCategory: NEW_TAB_COMMANDS | null =
                    newTabSceneDataInclude.length === 1 && newTabSceneDataInclude[0] !== 'all'
                        ? newTabSceneDataInclude[0]
                        : null

                return (section: string): number => {
                    const manualLimit = sectionItemLimits[section]
                    if (manualLimit !== undefined) {
                        return manualLimit
                    }

                    if (singleSelectedCategory && section === singleSelectedCategory) {
                        return SINGLE_CATEGORY_SECTION_LIMIT
                    }

                    return INITIAL_SECTION_LIMIT
                }
            },
        ],
        itemsGrid: [
            (s) => [
                s.featureFlags,
                s.projectFolderItems,
                s.projectTreeSearchItems,
                s.aiSearchItems,
                s.sceneLogViewsByRef,
                s.newLogViewsByRef,
            ],
            (
                featureFlags: any,
                projectFolderItems: NewTabTreeDataItem[],
                projectTreeSearchItems: NewTabTreeDataItem[],
                aiSearchItems: NewTabTreeDataItem[],
                sceneLogViewsByRef: Record<string, string>,
                newLogViewsByRef: Record<string, string>
            ): NewTabTreeDataItem[] => {
                const registerSceneKey = (map: Map<string, string>, key?: string | null, sceneKey?: string): void => {
                    if (!key || !sceneKey || map.has(key)) {
                        return
                    }
                    map.set(key, sceneKey)
                }

                const sceneKeyByType = new Map<string, string>()

                const getSceneKeyForFs = (fs: FileSystemImport): string | null => {
                    if (fs.sceneKey) {
                        return fs.sceneKey
                    }
                    if (fs.type) {
                        const direct = sceneKeyByType.get(fs.type)
                        if (direct) {
                            return direct
                        }
                        const baseType = fs.type.split('/')?.[0]
                        if (baseType) {
                            const base = sceneKeyByType.get(baseType)
                            if (base) {
                                return base
                            }
                        }
                    }
                    if ('iconType' in fs && fs.iconType) {
                        const fromIcon = sceneKeyByType.get(fs.iconType as string)
                        if (fromIcon) {
                            return fromIcon
                        }
                    }
                    return null
                }

                const getLastViewedAt = (sceneKey?: string | null): string | null =>
                    sceneKey ? (sceneLogViewsByRef[sceneKey] ?? null) : null

                const getLastViewedAtForHref = (href?: string | null): string | null =>
                    href ? (newLogViewsByRef[href] ?? null) : null

                const defaultProducts = getDefaultTreeProducts()
                const defaultData = getDefaultTreeData()

                defaultProducts.forEach((fs) => {
                    if (fs.sceneKey) {
                        registerSceneKey(sceneKeyByType, fs.type, fs.sceneKey)
                        if (fs.type?.includes('/')) {
                            registerSceneKey(sceneKeyByType, fs.type.split('/')[0], fs.sceneKey)
                        }
                        if ('iconType' in fs) {
                            registerSceneKey(sceneKeyByType, fs.iconType as string | undefined, fs.sceneKey)
                        }
                    }
                })

                defaultData.forEach((fs) => {
                    if (fs.sceneKey) {
                        registerSceneKey(sceneKeyByType, fs.type, fs.sceneKey)
                        if (fs.type?.includes('/')) {
                            registerSceneKey(sceneKeyByType, fs.type.split('/')[0], fs.sceneKey)
                        }
                        if ('iconType' in fs) {
                            registerSceneKey(sceneKeyByType, fs.iconType as string | undefined, fs.sceneKey)
                        }
                    }
                })

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
                        lastViewedAt: getLastViewedAtForHref(fs.href),
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const newDataItems = getDefaultTreeNew()
                    .filter(({ path }) => path.startsWith('Data/'))
                    .map((fs, index) => ({
                        id: `new-data-${index}`,
                        name: 'New ' + capitalizeFirstLetter(fs.path.substring(5).toLowerCase()),
                        category: 'create-new' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                        lastViewedAt: getLastViewedAtForHref(fs.href),
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
                        lastViewedAt: getLastViewedAtForHref(fs.href),
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const products = [...defaultProducts, ...getDefaultTreePersons()]
                    .map((fs, index) => ({
                        id: `product-${index}`,
                        name: fs.path,
                        category: 'apps' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                        lastViewedAt: getLastViewedAt(getSceneKeyForFs(fs)),
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])
                    .toSorted((a, b) => a.name.localeCompare(b.name))

                const manualProductItems: NewTabTreeDataItem[] = [
                    {
                        id: 'product-activity',
                        name: 'Activity',
                        category: 'apps',
                        href: urls.activity(ActivityTab.ExploreEvents),
                        icon: <IconActivity />,
                        record: {
                            type: 'link',
                            path: 'Activity',
                            href: urls.activity(ActivityTab.ExploreEvents),
                        },
                        lastViewedAt: getLastViewedAtForHref(urls.activity(ActivityTab.ExploreEvents)),
                    },
                ]

                const sortedProducts = sortByLastViewedAt([...products, ...manualProductItems])

                const data = defaultData
                    .map((fs, index) => ({
                        id: `data-${index}`,
                        name: fs.path,
                        category: 'data-management' as NEW_TAB_CATEGORY_ITEMS,
                        href: fs.href,
                        flag: fs.flag,
                        icon: getIconForFileSystemItem(fs),
                        record: fs,
                        // TODO: re-enable when all data-management items support it
                        // lastViewedAt: getLastViewedAt(getSceneKeyForFs(fs)),
                    }))
                    .filter(({ flag }) => !flag || featureFlags[flag as keyof typeof featureFlags])

                const manualDataItems: NewTabTreeDataItem[] = [
                    {
                        id: 'data-settings',
                        name: 'Project settings',
                        category: 'data-management',
                        href: urls.settings(),
                        icon: <IconGear />,
                        record: {
                            type: 'link',
                            path: 'Project settings',
                            href: urls.settings(),
                        },
                        lastViewedAt: getLastViewedAtForHref(urls.settings()),
                    },
                    {
                        id: 'data-toolbar',
                        name: 'Toolbar',
                        category: 'data-management',
                        href: urls.toolbarLaunch(),
                        icon: <IconToolbar />,
                        record: {
                            type: 'link',
                            path: 'Toolbar',
                            href: urls.toolbarLaunch(),
                        },
                        lastViewedAt: getLastViewedAtForHref(urls.toolbarLaunch()),
                    },
                ]

                const sortedData = sortByLastViewedAt([...data, ...manualDataItems])

                const sortedNewInsightItems = sortByLastViewedAt(newInsightItems)
                const sortedNewDataItems = sortByLastViewedAt(newDataItems)
                const sortedNewOtherItems = sortByLastViewedAt(newOtherItems)

                return sortByLastViewedAt([
                    ...projectFolderItems,
                    ...aiSearchItems,
                    ...projectTreeSearchItems,
                    {
                        id: 'new-sql-query',
                        name: 'New SQL query',
                        category: 'create-new',
                        icon: <IconDatabase />,
                        href: '/sql',
                        record: { type: 'query', path: 'New SQL query' },
                        lastViewedAt: getLastViewedAtForHref('/sql'),
                    },
                    ...sortedNewInsightItems,
                    ...sortedNewOtherItems,
                    ...sortedProducts,
                    ...sortedData,
                    ...sortedNewDataItems,
                    {
                        id: 'new-hog-program',
                        name: 'New Hog program',
                        category: 'create-new',
                        icon: <IconHogQL />,
                        href: '/debug/hog',
                        record: { type: 'hog', path: 'New Hog program' },
                        lastViewedAt: getLastViewedAtForHref('/debug/hog'),
                    },
                ])
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
                s.projectFolderItems,
                s.personSearchItems,
                s.groupSearchItems,
                s.eventDefinitionSearchItems,
                s.propertyDefinitionSearchItems,
                s.aiSearchItems,
                s.getSectionItemLimit,
            ],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                newTabSceneDataInclude: NEW_TAB_COMMANDS[],
                projectFolderItems: NewTabTreeDataItem[],
                personSearchItems: NewTabTreeDataItem[],
                groupSearchItems: NewTabTreeDataItem[],
                eventDefinitionSearchItems: NewTabTreeDataItem[],
                propertyDefinitionSearchItems: NewTabTreeDataItem[],
                aiSearchItems: NewTabTreeDataItem[],
                getSectionItemLimit: (section: string) => number
            ): Record<string, NewTabTreeDataItem[]> => {
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
                                item.name.toLowerCase().includes(chunk) ||
                                item.category.toLowerCase().includes(chunk) ||
                                item.record?.type?.toLowerCase().includes(chunk)
                        )
                    )
                }

                // Check if "all" is selected
                const showAll = newTabSceneDataInclude.includes('all')

                const filteredProjectFolderItems = (() => {
                    if (!projectFolderItems.length) {
                        return projectFolderItems
                    }

                    const [projectRootItem, ...otherProjectFolderItems] = projectFolderItems

                    if (!searchLower) {
                        return projectFolderItems
                    }

                    const projectRootMatches = filterBySearch([projectRootItem]).length > 0
                    const filtered = filterBySearch(otherProjectFolderItems)

                    return projectRootMatches ? [projectRootItem, ...filtered] : filtered
                })()
                const filteredPersonItems = filterBySearch(personSearchItems)
                const filteredGroupItems = filterBySearch(groupSearchItems)
                const filteredEventDefinitionItems = filterBySearch(eventDefinitionSearchItems)
                const filteredPropertyDefinitionItems = filterBySearch(propertyDefinitionSearchItems)
                const filteredAiSearchItems = filterBySearch(aiSearchItems)

                // Group items by category and filter based on what's selected
                const grouped: Record<string, NewTabTreeDataItem[]> = {}

                // Add persons section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('project-folders')) {
                    const limit = getSectionItemLimit('project-folders')
                    grouped['project-folders'] = filteredProjectFolderItems.slice(0, limit)
                }
                if (showAll || newTabSceneDataInclude.includes('persons')) {
                    const limit = getSectionItemLimit('persons')
                    grouped['persons'] = filteredPersonItems.slice(0, limit)
                }
                if (showAll || newTabSceneDataInclude.includes('groups')) {
                    const limit = getSectionItemLimit('groups')
                    grouped['groups'] = filteredGroupItems.slice(0, limit)
                }
                // Add event definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('eventDefinitions')) {
                    const limit = getSectionItemLimit('eventDefinitions')
                    grouped['eventDefinitions'] = filteredEventDefinitionItems.slice(0, limit)
                }

                // Add property definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('propertyDefinitions')) {
                    const limit = getSectionItemLimit('propertyDefinitions')
                    grouped['propertyDefinitions'] = filteredPropertyDefinitionItems.slice(0, limit)
                }

                // Add each category only if it's selected or if "all" is selected
                if (showAll || newTabSceneDataInclude.includes('create-new')) {
                    const limit = getSectionItemLimit('create-new')
                    grouped['create-new'] = sortByLastViewedAt(
                        filterBySearch(itemsGrid.filter((item) => item.category === 'create-new'))
                    ).slice(0, limit)
                }

                if (showAll || newTabSceneDataInclude.includes('apps')) {
                    const limit = getSectionItemLimit('apps')
                    grouped['apps'] = sortByLastViewedAt(
                        filterBySearch(itemsGrid.filter((item) => item.category === 'apps'))
                    ).slice(0, limit)
                }

                if (showAll || newTabSceneDataInclude.includes('data-management')) {
                    const limit = getSectionItemLimit('data-management')
                    grouped['data-management'] = sortByLastViewedAt(
                        filterBySearch(itemsGrid.filter((item) => item.category === 'data-management'))
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
                    grouped['askAI'] = filteredAiSearchItems.slice(0, limit)
                }

                return grouped
            },
        ],
        newTabSceneDataGroupedItemsFullData: [
            (s) => [
                s.itemsGrid,
                s.search,
                s.newTabSceneDataInclude,
                s.projectFolderItems,
                s.personSearchItems,
                s.groupSearchItems,
                s.eventDefinitionSearchItems,
                s.propertyDefinitionSearchItems,
                s.aiSearchItems,
            ],
            (
                itemsGrid: NewTabTreeDataItem[],
                search: string,
                newTabSceneDataInclude: NEW_TAB_COMMANDS[],
                projectFolderItems: NewTabTreeDataItem[],
                personSearchItems: NewTabTreeDataItem[],
                groupSearchItems: NewTabTreeDataItem[],
                eventDefinitionSearchItems: NewTabTreeDataItem[],
                propertyDefinitionSearchItems: NewTabTreeDataItem[],
                aiSearchItems: NewTabTreeDataItem[]
            ): Record<string, number> => {
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

                const filteredProjectFolderItems = (() => {
                    if (!searchLower) {
                        return projectFolderItems
                    }
                    const filtered = filterBySearch(projectFolderItems.slice(1))
                    return projectFolderItems.length > 0 ? [projectFolderItems[0], ...filtered] : filtered
                })()
                const filteredPersonItems = filterBySearch(personSearchItems)
                const filteredGroupItems = filterBySearch(groupSearchItems)
                const filteredEventDefinitionItems = filterBySearch(eventDefinitionSearchItems)
                const filteredPropertyDefinitionItems = filterBySearch(propertyDefinitionSearchItems)
                const filteredAiSearchItems = filterBySearch(aiSearchItems)

                // Track full counts for each section
                const fullCounts: Record<string, number> = {}

                // Add persons section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('project-folders')) {
                    fullCounts['project-folders'] = filteredProjectFolderItems.length
                }
                if (showAll || newTabSceneDataInclude.includes('persons')) {
                    fullCounts['persons'] = filteredPersonItems.length
                }
                if (showAll || newTabSceneDataInclude.includes('groups')) {
                    fullCounts['groups'] = filteredGroupItems.length
                }
                // Add event definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('eventDefinitions')) {
                    fullCounts['eventDefinitions'] = filteredEventDefinitionItems.length
                }

                // Add property definitions section if filter is enabled
                if (showAll || newTabSceneDataInclude.includes('propertyDefinitions')) {
                    fullCounts['propertyDefinitions'] = filteredPropertyDefinitionItems.length
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
                    fullCounts['askAI'] = filteredAiSearchItems.length
                }

                return fullCounts
            },
        ],
        allCategories: [
            (s) => [
                s.newTabSceneDataGroupedItems,
                s.newTabSceneDataInclude,
                s.categoryLoadingStates,
                s.search,
                s.firstNoResultsSearchPrefixes,
            ],
            (
                newTabSceneDataGroupedItems: Record<string, NewTabTreeDataItem[]>,
                newTabSceneDataInclude: NEW_TAB_COMMANDS[],
                categoryLoadingStates: Record<NEW_TAB_CATEGORY_ITEMS, boolean>,
                search: string,
                firstNoResultsSearchPrefixes: Record<NewTabSearchDataset, string | null>
            ): CategoryWithItems[] => {
                const orderedSections: string[] = []
                const showAll = newTabSceneDataInclude.includes('all')

                // Add sections in a useful order
                const mainSections = ['project-folders', 'recents', 'create-new', 'apps', 'data-management']
                mainSections.forEach((section) => {
                    if (showAll || newTabSceneDataInclude.includes(section as NEW_TAB_COMMANDS)) {
                        orderedSections.push(section)
                    }
                })
                if (showAll || newTabSceneDataInclude.includes('persons')) {
                    orderedSections.push('persons')
                }
                if (showAll || newTabSceneDataInclude.includes('groups')) {
                    orderedSections.push('groups')
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

                const trimmedSearch = search.trim()
                const hasPrefixNoResults = (dataset: NewTabSearchDataset): boolean => {
                    const prefix = firstNoResultsSearchPrefixes[dataset]
                    return (
                        !!prefix &&
                        trimmedSearch !== '' &&
                        trimmedSearch.length > prefix.length &&
                        trimmedSearch.startsWith(prefix)
                    )
                }

                const categories = orderedSections
                    .map((section) => {
                        const key = section as NEW_TAB_CATEGORY_ITEMS
                        const items = newTabSceneDataGroupedItems[section] || []
                        const isLoading = categoryLoadingStates[key] || false
                        const shouldHideForPrefix =
                            (key === 'project-folders' && hasPrefixNoResults('projectFolders')) ||
                            (key === 'recents' && hasPrefixNoResults('recents')) ||
                            (key === 'persons' && hasPrefixNoResults('persons')) ||
                            (key === 'eventDefinitions' && hasPrefixNoResults('eventDefinitions')) ||
                            (key === 'propertyDefinitions' && hasPrefixNoResults('propertyDefinitions'))

                        return {
                            key,
                            items,
                            isLoading: shouldHideForPrefix ? false : isLoading,
                            shouldHideForPrefix,
                        }
                    })
                    .filter(({ items, isLoading, shouldHideForPrefix }) => {
                        if (showAll) {
                            if (shouldHideForPrefix) {
                                return false
                            }
                            return items.length > 0 || isLoading
                        }
                        return true
                    })
                    .map(({ shouldHideForPrefix, ...rest }) => rest)

                const [categoriesWithResults, emptyCategories] = categories.reduce(
                    (acc, category) => {
                        if (category.items.length === 0) {
                            acc[1].push(category)
                        } else {
                            acc[0].push(category)
                        }
                        return acc
                    },
                    [[], []] as [CategoryWithItems[], CategoryWithItems[]]
                )

                return [...categoriesWithResults, ...emptyCategories]
            },
        ],
        firstCategoryWithResults: [
            (s) => [s.allCategories],
            (allCategories: CategoryWithItems[]): string | null => {
                for (const { key, items } of allCategories) {
                    // Check if any category has items
                    if (items.length > 0) {
                        return key
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
        loadMoreRecents: () => {
            if (values.recentsLoading) {
                return
            }

            const currentLimit = values.getSectionItemLimit('recents')
            if (Number.isFinite(currentLimit)) {
                actions.setSectionItemLimit('recents', currentLimit + PAGINATION_LIMIT)
            }

            if (values.recents.hasMore) {
                actions.loadRecents({ offset: values.recents.results.length })
            }
        },
        setProjectPath: ({ projectPath }) => {
            const folder = normalizeProjectPath(projectPath)
            actions.loadFolder(folder)
            if (projectPath === null) {
                actions.clearProjectTreeSearch()
            }
        },
        loadMoreFileBrowser: () => {
            const folder = values.projectFolderPath
            const searchTerm = values.search.trim()
            if (searchTerm) {
                actions.loadProjectTreeSearchResults(searchTerm, values.projectTreeSearchResults.results.length)
                return
            }
            actions.loadFolder(folder)
        },
        logCreateNewItem: async ({ href }) => {
            if (!href) {
                return
            }

            try {
                await api.fileSystemLogView.create({ type: 'create-new', ref: href })
            } catch (error) {
                console.error('Failed to log create new item usage:', error)
            }

            actions.loadNewLogViews()
        },
        triggerSearchForIncludedItems: () => {
            const searchTerm = values.search.trim()

            // Expand 'all' to include all data types
            const itemsToProcess = values.newTabSceneDataInclude.includes('all')
                ? ['project-folders', 'persons', 'groups', 'eventDefinitions', 'propertyDefinitions', 'askAI']
                : values.newTabSceneDataInclude

            itemsToProcess.forEach((item) => {
                if (searchTerm !== '') {
                    if (item === 'project-folders') {
                        actions.debouncedProjectFolderSearch(searchTerm)
                    } else if (item === 'persons') {
                        actions.debouncedPersonSearch(searchTerm)
                    } else if (item === 'groups') {
                        actions.debouncedGroupSearch(searchTerm)
                    } else if (item === 'eventDefinitions') {
                        actions.debouncedEventDefinitionSearch(searchTerm)
                    } else if (item === 'propertyDefinitions') {
                        actions.debouncedPropertyDefinitionSearch(searchTerm)
                    }
                } else {
                    // Load initial data when no search term
                    if (item === 'project-folders') {
                        actions.loadProjectFolderSearchResultsSuccess([])
                    } else if (item === 'persons') {
                        actions.loadInitialPersons({})
                    } else if (item === 'groups') {
                        actions.loadInitialGroups()
                    } else if (item === 'eventDefinitions') {
                        actions.loadInitialEventDefinitions({})
                    } else if (item === 'propertyDefinitions') {
                        actions.loadInitialPropertyDefinitions({})
                    }
                }
            })
        },
        onSubmit: () => {
            const selected = values.selectedItem
            if (selected) {
                if (selected.category === 'askAI' && selected.record?.searchTerm) {
                    actions.askAI(selected.record.searchTerm)
                } else if (selected.href) {
                    if (selected.category === 'create-new') {
                        actions.logCreateNewItem(selected.href)
                    }
                    router.actions.push(selected.href)
                }
            }
        },
        setSearch: ({ search }) => {
            if (values.isFileBrowserMode) {
                if (search.trim()) {
                    actions.setProjectTreeSearchTerm(search)
                } else {
                    actions.clearProjectTreeSearch()
                }
                return
            }
            actions.loadRecents()
            actions.triggerSearchForIncludedItems()
        },
        toggleNewTabSceneDataInclude: ({ item }) => {
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
                } else if (item === 'groups') {
                    actions.loadGroupSearchResultsSuccess({})
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
        debouncedProjectFolderSearch: async ({ searchTerm }, breakpoint) => {
            const trimmed = searchTerm.trim()
            const noResultsPrefix = values.firstNoResultsSearchPrefixes.projectFolders

            if (trimmed === '') {
                actions.loadProjectFolderSearchResultsSuccess([])
                actions.setFirstNoResultsSearchPrefix('projectFolders', null)
                return
            }

            if (noResultsPrefix && trimmed.length > noResultsPrefix.length && trimmed.startsWith(noResultsPrefix)) {
                actions.loadProjectFolderSearchResultsSuccess([])
                return
            }

            await breakpoint(300)
            actions.loadProjectFolderSearchResults(trimmed)
        },
        debouncedPersonSearch: async ({ searchTerm }, breakpoint) => {
            // Manually trigger the search and handle the result
            const trimmed = searchTerm.trim()
            const noResultsPrefix = values.firstNoResultsSearchPrefixes.persons

            if (
                trimmed &&
                noResultsPrefix &&
                trimmed.length > noResultsPrefix.length &&
                trimmed.startsWith(noResultsPrefix)
            ) {
                actions.loadPersonSearchResultsSuccess([])
                return
            }

            await breakpoint(300)

            try {
                const response = await api.persons.list({ search: trimmed, limit: 5 })
                breakpoint()

                // Manually set the results instead of relying on the loader
                actions.loadPersonSearchResultsSuccess(response.results)
                if (trimmed) {
                    actions.setFirstNoResultsSearchPrefix('persons', response.results.length === 0 ? trimmed : null)
                }
            } catch (error: any) {
                if (!isBreakpoint(error)) {
                    console.error('Person search failed:', error)
                    actions.loadPersonSearchResultsFailure(error as string)
                }
            }
        },
        debouncedEventDefinitionSearch: async ({ searchTerm }, breakpoint) => {
            const trimmed = searchTerm.trim()
            const noResultsPrefix = values.firstNoResultsSearchPrefixes.eventDefinitions

            if (
                trimmed &&
                noResultsPrefix &&
                trimmed.length > noResultsPrefix.length &&
                trimmed.startsWith(noResultsPrefix)
            ) {
                actions.loadEventDefinitionSearchResultsSuccess([])
                return
            }
            await breakpoint(300)

            try {
                const response = await api.eventDefinitions.list({
                    search: trimmed,
                    limit: 5,
                })
                breakpoint()
                actions.loadEventDefinitionSearchResultsSuccess(response.results ?? [])
                if (trimmed) {
                    actions.setFirstNoResultsSearchPrefix(
                        'eventDefinitions',
                        (response.results ?? []).length === 0 ? trimmed : null
                    )
                }
            } catch (error: any) {
                if (!isBreakpoint(error)) {
                    console.error('Event definition search failed:', error)
                    actions.loadEventDefinitionSearchResultsFailure(error as string)
                }
            }
        },
        debouncedPropertyDefinitionSearch: async ({ searchTerm }, breakpoint) => {
            const trimmed = searchTerm.trim()
            const noResultsPrefix = values.firstNoResultsSearchPrefixes.propertyDefinitions
            if (
                trimmed &&
                noResultsPrefix &&
                trimmed.length > noResultsPrefix.length &&
                trimmed.startsWith(noResultsPrefix)
            ) {
                actions.loadPropertyDefinitionSearchResultsSuccess([])
                return
            }
            await breakpoint(300)
            try {
                const response = await api.propertyDefinitions.list({
                    search: trimmed,
                    limit: 5,
                })
                breakpoint()
                actions.loadPropertyDefinitionSearchResultsSuccess(response.results ?? [])
                if (trimmed) {
                    actions.setFirstNoResultsSearchPrefix(
                        'propertyDefinitions',
                        (response.results ?? []).length === 0 ? trimmed : null
                    )
                }
            } catch (error: any) {
                if (!isBreakpoint(error)) {
                    console.error('Property definition search failed:', error)
                    actions.loadPropertyDefinitionSearchResultsFailure(error as string)
                }
            }
        },
        debouncedGroupSearch: async ({ searchTerm }, breakpoint) => {
            const trimmed = searchTerm.trim()
            const noResultsPrefix = values.firstNoResultsSearchPrefixes.groups

            if (
                trimmed &&
                noResultsPrefix &&
                trimmed.length > noResultsPrefix.length &&
                trimmed.startsWith(noResultsPrefix)
            ) {
                actions.loadGroupSearchResultsSuccess({})
                return
            }
            await breakpoint(300)
            actions.loadGroupSearchResults({ searchTerm })
        },
    })),
    tabAwareActionToUrl(({ values }) => {
        const buildParams = (): Record<string, any> => {
            const includeItems = values.newTabSceneDataInclude.filter((item) => item !== 'all')
            const includeParam = includeItems.length > 0 ? includeItems.join(',') : undefined

            return {
                search: values.search || undefined,
                category: undefined,
                include: includeParam,
                projectPath: values.projectPath || undefined,
            }
        }

        return {
            setSearch: () => [router.values.location.pathname, buildParams()],
            setSelectedCategory: () => [router.values.location.pathname, buildParams()],
            setNewTabSceneDataInclude: () => [router.values.location.pathname, buildParams()],
            toggleNewTabSceneDataInclude: () => [router.values.location.pathname, buildParams()],
            setProjectPath: () => [router.values.location.pathname, buildParams()],
        }
    }),
    tabAwareUrlToAction(({ actions, values }) => ({
        [urls.newTab()]: (_, searchParams) => {
            // Update search if URL search param differs from current state
            if (searchParams.search && searchParams.search !== values.search) {
                actions.setSearch(String(searchParams.search))

                // Trigger searches for already included items when search term changes
                if (values.newTabSceneDataInclude.length > 0) {
                    const searchTerm = String(searchParams.search).trim()
                    if (searchTerm !== '') {
                        // Expand 'all' to include all data types
                        const itemsToProcess = values.newTabSceneDataInclude.includes('all')
                            ? ['persons', 'groups', 'eventDefinitions', 'propertyDefinitions']
                            : values.newTabSceneDataInclude

                        itemsToProcess.forEach((item) => {
                            if (item === 'persons') {
                                actions.debouncedPersonSearch(searchTerm)
                            } else if (item === 'groups') {
                                actions.debouncedGroupSearch(searchTerm)
                            } else if (item === 'eventDefinitions') {
                                actions.debouncedEventDefinitionSearch(searchTerm)
                            } else if (item === 'propertyDefinitions') {
                                actions.debouncedPropertyDefinitionSearch(searchTerm)
                            }
                        })
                    }
                }
            }

            // Update include array if URL param differs from current state
            const includeFromUrlRaw = searchParams.include
                ? (searchParams.include as string)
                      .split(',')
                      .filter((item): item is NEW_TAB_COMMANDS =>
                          [
                              'all',
                              'project-folders',
                              'create-new',
                              'apps',
                              'data-management',
                              'recents',
                              'persons',
                              'groups',
                              'eventDefinitions',
                              'propertyDefinitions',
                              'askAI',
                          ].includes(item)
                      )
                : null

            if (includeFromUrlRaw !== null) {
                const currentIncludeString = values.newTabSceneDataInclude.slice().sort().join(',')
                const urlIncludeString = includeFromUrlRaw.slice().sort().join(',')

                if (currentIncludeString !== urlIncludeString) {
                    actions.setNewTabSceneDataInclude(includeFromUrlRaw)

                    // Load data for included items
                    const searchTerm = searchParams.search ? String(searchParams.search).trim() : ''

                    // Expand 'all' to include all data types
                    const itemsToProcess = includeFromUrlRaw.includes('all')
                        ? ['persons', 'groups', 'eventDefinitions', 'propertyDefinitions', 'askAI']
                        : includeFromUrlRaw

                    itemsToProcess.forEach((item) => {
                        if (searchTerm !== '') {
                            // If there's a search term, trigger search for data items only
                            if (item === 'persons') {
                                actions.debouncedPersonSearch(searchTerm)
                            } else if (item === 'groups') {
                                actions.debouncedGroupSearch(searchTerm)
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
                            } else if (item === 'groups') {
                                actions.loadInitialGroups()
                            } else if (item === 'eventDefinitions') {
                                actions.loadInitialEventDefinitions({})
                            } else if (item === 'propertyDefinitions') {
                                actions.loadInitialPropertyDefinitions({})
                            }
                        }
                    })
                }
            }

            const projectPathParam = searchParams.projectPath
            let decodedProjectPath: string | null = null
            if (typeof projectPathParam === 'string') {
                try {
                    decodedProjectPath = decodeURIComponent(projectPathParam)
                } catch {
                    decodedProjectPath = projectPathParam
                }
            }
            if (decodedProjectPath !== values.projectPath) {
                actions.setProjectPath(decodedProjectPath)
            }

            // Reset search, category, and include array to defaults if no URL params
            if (!searchParams.search && values.search) {
                actions.setSearch('')
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
        actions.loadSceneLogViews()
        actions.loadNewLogViews()
        actions.loadRecents()

        // Load initial data for data sections when "all" is selected by default
        if (values.newTabSceneDataInclude.includes('all')) {
            actions.loadInitialPersons({})
            actions.loadInitialGroups()
            actions.loadInitialEventDefinitions({})
            actions.loadInitialPropertyDefinitions({})
        }
    }),
])
