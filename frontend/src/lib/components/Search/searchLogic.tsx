import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import { IconClock } from '@posthog/icons'

import api from 'lib/api'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { preflightLogic } from 'scenes/PreflightCheck/preflightLogic'
import { urls } from 'scenes/urls'

import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { groupsModel } from '~/models/groupsModel'
import { getTreeItemsMetadata, getTreeItemsProducts } from '~/products'
import { FileSystemEntry, FileSystemViewLogEntry, GroupsQueryResponse } from '~/queries/schema/schema-general'
import { ActivityTab, Group, GroupTypeIndex, PersonType, SearchResponse } from '~/types'

import type { searchLogicType } from './searchLogicType'

// Types for command search results
export interface SearchItem {
    id: string
    name: string
    displayName?: string
    category: string
    productCategory?: string | null
    href?: string
    icon?: React.ReactNode
    lastViewedAt?: string | null
    groupNoun?: string | null
    itemType?: string | null
    tags?: string[]
    record?: Record<string, unknown>
}

export interface SearchCategory {
    key: string
    items: SearchItem[]
    isLoading: boolean
}

export interface SearchLogicProps {
    logicKey: string
}

export type GroupQueryResult = Pick<Group, 'group_key' | 'group_properties'>

export const RECENTS_LIMIT = 5
const SEARCH_LIMIT = 5

function mapGroupQueryResponse(response: GroupsQueryResponse): GroupQueryResult[] {
    return response.results.map((row) => ({
        group_key: row[response.columns.indexOf('key')],
        group_properties: {
            name: row[response.columns.indexOf('group_name')],
        },
    }))
}

export const searchLogic = kea<searchLogicType>([
    path((logicKey) => ['lib', 'components', 'Search', 'searchLogic', logicKey]),
    props({} as SearchLogicProps),
    key((props) => props.logicKey),
    connect({
        values: [
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            commandLogic,
            ['isCommandOpen'],
            featureFlagLogic,
            ['featureFlags'],
            preflightLogic,
            ['isDev'],
        ],
    }),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    loaders(({ values }) => ({
        sceneLogViews: [
            [] as FileSystemViewLogEntry[],
            {
                loadSceneLogViews: async () => {
                    return await api.fileSystemLogView.list({ type: 'scene' })
                },
            },
        ],
        recents: [
            { results: [], hasMore: false } as { results: FileSystemEntry[]; hasMore: boolean },
            {
                loadRecents: async ({ search }: { search: string }, breakpoint) => {
                    const searchTerm = search.trim()

                    const response = await api.fileSystem.list({
                        search: searchTerm || undefined,
                        limit: RECENTS_LIMIT + 1,
                        orderBy: '-last_viewed_at',
                        notType: 'folder',
                    })
                    breakpoint()

                    return {
                        results: response.results.slice(0, RECENTS_LIMIT),
                        hasMore: response.results.length > RECENTS_LIMIT,
                    }
                },
            },
        ],
        unifiedSearchResults: [
            null as SearchResponse | null,
            {
                loadUnifiedSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return null
                    }

                    const response = await api.search.list({ q: trimmed })
                    breakpoint()

                    return response
                },
            },
        ],
        groupSearchResults: [
            {} as Partial<Record<GroupTypeIndex, GroupQueryResult[]>>,
            {
                loadGroupSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return {}
                    }

                    const groupTypesList = Array.from(values.groupTypes.values())
                    if (groupTypesList.length === 0) {
                        return {}
                    }

                    const results = await Promise.allSettled(
                        groupTypesList.map((groupType) =>
                            api.groups.listClickhouse({
                                group_type_index: groupType.group_type_index,
                                search: trimmed,
                                limit: SEARCH_LIMIT,
                            })
                        )
                    )

                    breakpoint()

                    return Object.fromEntries(
                        results
                            .map((result, index) => [groupTypesList[index], result] as const)
                            .filter(([, result]) => result.status === 'fulfilled')
                            .map(([groupType, result]) => [
                                groupType.group_type_index,
                                mapGroupQueryResponse((result as PromiseFulfilledResult<GroupsQueryResponse>).value),
                            ])
                    ) as Record<GroupTypeIndex, GroupQueryResult[]>
                },
            },
        ],
        personSearchResults: [
            [] as PersonType[],
            {
                loadPersonSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return []
                    }

                    const response = await api.persons.list({ search: trimmed, limit: SEARCH_LIMIT })
                    breakpoint()

                    return response.results
                },
            },
        ],
        playlistSearchResults: [
            [] as FileSystemEntry[],
            {
                loadPlaylistSearchResults: async ({ searchTerm }: { searchTerm: string }, breakpoint) => {
                    const trimmed = searchTerm.trim()

                    if (trimmed === '') {
                        return []
                    }

                    const response = await api.fileSystem.list({
                        search: trimmed,
                        type: 'session_recording_playlist',
                        limit: SEARCH_LIMIT,
                    })
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
        searchPending: [
            false,
            {
                setSearch: (_, { search }) => search.trim() !== '',
                loadRecentsSuccess: () => false,
                loadRecentsFailure: () => false,
                loadUnifiedSearchResultsSuccess: () => false,
                loadUnifiedSearchResultsFailure: () => false,
            },
        ],
        recentsHasLoaded: [
            false,
            {
                loadRecentsSuccess: () => true,
                loadRecentsFailure: () => true,
            },
        ],
        sceneLogViewsHasLoaded: [
            false,
            {
                loadSceneLogViewsSuccess: () => true,
                loadSceneLogViewsFailure: () => true,
            },
        ],
    }),
    selectors({
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
        isSearching: [
            (s) => [
                s.recentsLoading,
                s.unifiedSearchResultsLoading,
                s.groupSearchResultsLoading,
                s.personSearchResultsLoading,
                s.playlistSearchResultsLoading,
                s.searchPending,
                s.search,
            ],
            (
                recentsLoading: boolean,
                unifiedSearchResultsLoading: boolean,
                groupSearchResultsLoading: boolean,
                personSearchResultsLoading: boolean,
                playlistSearchResultsLoading: boolean,
                searchPending: boolean,
                search: string
            ): boolean =>
                (recentsLoading ||
                    unifiedSearchResultsLoading ||
                    groupSearchResultsLoading ||
                    personSearchResultsLoading ||
                    playlistSearchResultsLoading ||
                    searchPending) &&
                search.trim() !== '',
        ],
        recentItems: [
            (s) => [s.recents],
            (recents): SearchItem[] => {
                return recents.results.map((item) => {
                    const name = splitPath(item.path).pop()
                    return {
                        id: item.path,
                        name: name ? unescapePath(name) : item.path,
                        category: 'recents',
                        href: item.href || '#',
                        lastViewedAt: item.last_viewed_at ?? null,
                        itemType: item.type ?? null,
                        record: item as unknown as Record<string, unknown>,
                    }
                })
            },
        ],
        appsItems: [
            (s) => [s.featureFlags, s.isDev, s.sceneLogViewsByRef],
            (featureFlags, isDev, sceneLogViewsByRef): SearchItem[] => {
                const allProducts = getTreeItemsProducts()
                const filteredProducts = allProducts.filter((product) => {
                    if (!isDev && product.category === 'Unreleased') {
                        return false
                    }
                    if (product.flag && !(featureFlags as Record<string, boolean>)[product.flag]) {
                        return false
                    }
                    return true
                })

                const items: SearchItem[] = filteredProducts.map((product) => ({
                    id: `app-${product.path}`,
                    name: product.path,
                    displayName: product.path,
                    category: 'apps',
                    productCategory: product.category || null,
                    href: product.href || '#',
                    itemType: product.iconType || product.type || null,
                    tags: product.tags,
                    lastViewedAt: product.sceneKey ? (sceneLogViewsByRef[product.sceneKey] ?? null) : null,
                    record: {
                        type: product.type || product.iconType,
                        iconType: product.iconType,
                        iconColor: product.iconColor,
                    },
                }))

                // Add Activity manually
                const activityHref = urls.activity(ActivityTab.ExploreEvents)
                items.push({
                    id: 'app-activity',
                    name: 'Activity',
                    displayName: 'Activity',
                    category: 'apps',
                    productCategory: null,
                    href: activityHref,
                    icon: <IconClock />,
                    itemType: null,
                    tags: undefined,
                    lastViewedAt: sceneLogViewsByRef['Activity'] ?? null,
                    record: {
                        type: 'activity',
                        iconType: undefined,
                        iconColor: undefined,
                    },
                })

                // Sort by lastViewedAt (most recent first), items without lastViewedAt go to the end
                return items.sort((a, b) => {
                    if (!a.lastViewedAt && !b.lastViewedAt) {
                        return a.name.localeCompare(b.name)
                    }
                    if (!a.lastViewedAt) {
                        return 1
                    }
                    if (!b.lastViewedAt) {
                        return -1
                    }
                    return new Date(b.lastViewedAt).getTime() - new Date(a.lastViewedAt).getTime()
                })
            },
        ],
        dataManagementItems: [
            (s) => [s.featureFlags, s.isDev, s.sceneLogViewsByRef],
            (featureFlags, isDev, sceneLogViewsByRef): SearchItem[] => {
                const allMetadata = getTreeItemsMetadata()
                const filteredMetadata = allMetadata.filter((item) => {
                    if (!isDev && item.category === 'Unreleased') {
                        return false
                    }
                    if (item.flag && !(featureFlags as Record<string, boolean>)[item.flag]) {
                        return false
                    }
                    return true
                })

                const items = filteredMetadata.map((item) => ({
                    id: `data-management-${item.path}`,
                    name: item.path,
                    displayName: item.path,
                    category: 'data-management',
                    productCategory: item.category || null,
                    href: item.href || '#',
                    itemType: item.iconType || item.type || null,
                    tags: item.tags,
                    lastViewedAt: item.sceneKey ? (sceneLogViewsByRef[item.sceneKey] ?? null) : null,
                    record: {
                        type: item.type || item.iconType,
                        iconType: item.iconType,
                        iconColor: item.iconColor,
                    },
                }))

                // Sort by lastViewedAt (most recent first), items without lastViewedAt go to the end
                return items.sort((a, b) => {
                    if (!a.lastViewedAt && !b.lastViewedAt) {
                        return a.name.localeCompare(b.name)
                    }
                    if (!a.lastViewedAt) {
                        return 1
                    }
                    if (!b.lastViewedAt) {
                        return -1
                    }
                    return new Date(b.lastViewedAt).getTime() - new Date(a.lastViewedAt).getTime()
                })
            },
        ],
        groupItems: [
            (s) => [s.groupSearchResults, s.aggregationLabel],
            (groupSearchResults, aggregationLabel): SearchItem[] => {
                const items: SearchItem[] = []
                for (const [groupTypeIndexString, groups] of Object.entries(groupSearchResults)) {
                    const groupTypeIndex = parseInt(groupTypeIndexString, 10) as GroupTypeIndex
                    const noun = aggregationLabel(groupTypeIndex).singular
                    ;(groups as GroupQueryResult[]).forEach((group) => {
                        const display = group.group_properties?.name || group.group_key || String(group.group_key)
                        items.push({
                            id: `group-${groupTypeIndex}-${group.group_key}`,
                            name: `${noun}: ${display}`,
                            displayName: display,
                            category: 'groups',
                            href: `/groups/${groupTypeIndex}/${encodeURIComponent(group.group_key)}`,
                            groupNoun: noun,
                            itemType: 'group',
                            record: {
                                type: 'group',
                                groupTypeIndex,
                                groupKey: group.group_key,
                                groupNoun: noun,
                            },
                        })
                    })
                }
                return items
            },
        ],
        personItems: [
            (s) => [s.personSearchResults],
            (personSearchResults): SearchItem[] => {
                return personSearchResults
                    .filter((person) => person.uuid) // Skip persons without uuid to avoid invalid URLs
                    .map((person) => {
                        const personId = person.distinct_ids?.[0] || person.uuid
                        const displayName = person.properties?.email || person.properties?.name || personId

                        return {
                            id: `person-${person.uuid}`,
                            name: displayName,
                            displayName,
                            category: 'persons',
                            href: urls.personByUUID(person.uuid!),
                            itemType: 'person',
                            record: {
                                type: 'person',
                                uuid: person.uuid,
                                distinctIds: person.distinct_ids,
                            },
                        }
                    })
            },
        ],
        playlistItems: [
            (s) => [s.playlistSearchResults],
            (playlistSearchResults): SearchItem[] => {
                return playlistSearchResults.map((item) => {
                    const name = splitPath(item.path).pop()
                    return {
                        id: `playlist-${item.id}`,
                        name: name ? unescapePath(name) : item.path,
                        category: 'session_recording_playlist',
                        href: item.href || '#',
                        itemType: 'session_recording_playlist',
                        record: item as unknown as Record<string, unknown>,
                    }
                })
            },
        ],
        unifiedSearchItems: [
            (s) => [s.unifiedSearchResults],
            (unifiedSearchResults): Record<string, SearchItem[]> => {
                if (!unifiedSearchResults) {
                    return {}
                }

                const categoryItems: Record<string, SearchItem[]> = {}

                for (const result of unifiedSearchResults.results) {
                    const category = result.type
                    if (!categoryItems[category]) {
                        categoryItems[category] = []
                    }

                    let name = result.result_id
                    let href = ''

                    switch (result.type) {
                        case 'insight':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/insights/${result.result_id}`
                            break
                        case 'dashboard':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/dashboard/${result.result_id}`
                            break
                        case 'feature_flag':
                            name = (result.extra_fields.key as string) || result.result_id
                            href = `/feature_flags/${result.result_id}`
                            break
                        case 'experiment':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/experiments/${result.result_id}`
                            break
                        case 'early_access_feature':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/early_access_features/${result.result_id}`
                            break
                        case 'hog_flow':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/workflows/${result.result_id}/workflow`
                            break
                        case 'survey':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/surveys/${result.result_id}`
                            break
                        case 'notebook':
                            name = (result.extra_fields.title as string) || result.result_id
                            href = `/notebooks/${result.result_id}`
                            break
                        case 'cohort':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/cohorts/${result.result_id}`
                            break
                        case 'action':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/data-management/actions/${result.result_id}`
                            break
                        case 'event_definition':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/data-management/events/${result.result_id}`
                            break
                        case 'property_definition':
                            name = (result.extra_fields.name as string) || result.result_id
                            href = `/data-management/properties/${result.result_id}`
                            break
                    }

                    categoryItems[category].push({
                        id: `${result.type}-${result.result_id}`,
                        name,
                        category,
                        href,
                        itemType: result.type,
                        record: {
                            type: result.type,
                            ...result.extra_fields,
                        },
                    })
                }

                return categoryItems
            },
        ],
        allCategories: [
            (s) => [
                s.recentItems,
                s.appsItems,
                s.dataManagementItems,
                s.personItems,
                s.groupItems,
                s.playlistItems,
                s.unifiedSearchItems,
                s.recentsLoading,
                s.recentsHasLoaded,
                s.sceneLogViewsLoading,
                s.sceneLogViewsHasLoaded,
                s.personSearchResultsLoading,
                s.groupSearchResultsLoading,
                s.playlistSearchResultsLoading,
                s.unifiedSearchResultsLoading,
                s.search,
            ],
            (
                recentItems,
                appsItems,
                dataManagementItems,
                personItems,
                groupItems,
                playlistItems,
                unifiedSearchItems,
                recentsLoading,
                recentsHasLoaded,
                sceneLogViewsLoading,
                sceneLogViewsHasLoaded,
                personSearchResultsLoading,
                groupSearchResultsLoading,
                playlistSearchResultsLoading,
                unifiedSearchResultsLoading,
                search
            ): SearchCategory[] => {
                const categories: SearchCategory[] = []
                const hasSearch = search.trim() !== ''

                // Filter items by search term
                const filterBySearch = (items: SearchItem[]): SearchItem[] => {
                    if (!hasSearch) {
                        return items
                    }
                    const searchLower = search.toLowerCase()
                    const searchChunks = searchLower.split(' ').filter((s) => s)
                    return items.filter((item) =>
                        searchChunks.every(
                            (chunk) =>
                                item.name.toLowerCase().includes(chunk) || item.category.toLowerCase().includes(chunk)
                        )
                    )
                }

                // Always show recents first - show loading skeleton until first load completes
                const isRecentsLoading = recentsLoading || !recentsHasLoaded
                categories.push({
                    key: 'recents',
                    items: recentItems,
                    isLoading: isRecentsLoading,
                })

                // Filter apps and data management by search
                const isAppsLoading = sceneLogViewsLoading || !sceneLogViewsHasLoaded
                const filteredApps = filterBySearch(appsItems)
                const filteredDataManagement = filterBySearch(dataManagementItems)

                // Show apps if not searching or has matching results
                if (!hasSearch || filteredApps.length > 0) {
                    categories.push({
                        key: 'apps',
                        items: isAppsLoading ? [] : filteredApps,
                        isLoading: isAppsLoading,
                    })
                }

                // Show data management if not searching or has matching results
                if (!hasSearch || filteredDataManagement.length > 0) {
                    categories.push({
                        key: 'data-management',
                        items: isAppsLoading ? [] : filteredDataManagement,
                        isLoading: isAppsLoading,
                    })
                }

                // Only show unified search results when searching
                if (hasSearch) {
                    const unifiedLoading = unifiedSearchResultsLoading

                    // Add unified search categories
                    const categoryOrder = [
                        'insight',
                        'dashboard',
                        'feature_flag',
                        'experiment',
                        'early_access_feature',
                        'survey',
                        'notebook',
                        'cohort',
                        'action',
                        'event_definition',
                        'property_definition',
                        'hog_flow',
                    ]

                    for (const category of categoryOrder) {
                        const items = unifiedSearchItems[category] || []
                        if (items.length > 0 || unifiedLoading) {
                            categories.push({
                                key: category,
                                items,
                                isLoading: unifiedLoading && items.length === 0,
                            })
                        }
                    }

                    // Add session recording playlists
                    if (playlistItems.length > 0 || playlistSearchResultsLoading) {
                        categories.push({
                            key: 'session_recording_playlist',
                            items: playlistItems,
                            isLoading: playlistSearchResultsLoading,
                        })
                    }

                    // Add persons
                    if (personItems.length > 0 || personSearchResultsLoading) {
                        categories.push({
                            key: 'persons',
                            items: personItems,
                            isLoading: personSearchResultsLoading,
                        })
                    }

                    // Add groups
                    if (groupItems.length > 0 || groupSearchResultsLoading) {
                        categories.push({
                            key: 'groups',
                            items: groupItems,
                            isLoading: groupSearchResultsLoading,
                        })
                    }
                }

                return categories
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        setSearch: async ({ search }, breakpoint) => {
            await breakpoint(150)

            actions.loadRecents({ search })

            if (search.trim() !== '') {
                actions.loadUnifiedSearchResults({ searchTerm: search })
                actions.loadPersonSearchResults({ searchTerm: search })
                actions.loadGroupSearchResults({ searchTerm: search })
                actions.loadPlaylistSearchResults({ searchTerm: search })
            }
        },
        [commandLogic.actionTypes.openCommand]: () => {
            // Load recents only when modal opens, not on mount
            if (values.recents.results.length === 0) {
                actions.loadRecents({ search: '' })
            }
            // Load scene log views for app last viewed timestamps
            if (values.sceneLogViews.length === 0) {
                actions.loadSceneLogViews()
            }
        },
    })),
    afterMount(({ actions }) => {
        // Load scene log views on mount for app last viewed timestamps
        actions.loadSceneLogViews()
    }),
])
