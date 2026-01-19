import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'
import { commandLogic } from 'lib/components/Command/commandLogic'
import { urls } from 'scenes/urls'

import { splitPath, unescapePath } from '~/layout/panel-layout/ProjectTree/utils'
import { groupsModel } from '~/models/groupsModel'
import { FileSystemEntry, GroupsQueryResponse } from '~/queries/schema/schema-general'
import { Group, GroupTypeIndex, PersonType, SearchResponse } from '~/types'

import type { searchLogicType } from './searchLogicType'

// Types for command search results
export interface SearchItem {
    id: string
    name: string
    displayName?: string
    category: string
    href?: string
    icon?: React.ReactNode
    lastViewedAt?: string | null
    groupNoun?: string | null
    itemType?: string | null
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

const RECENTS_LIMIT = 5
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
        values: [groupsModel, ['groupTypes', 'aggregationLabel'], commandLogic, ['isCommandOpen']],
    }),
    actions({
        setSearch: (search: string) => ({ search }),
    }),
    loaders(({ values }) => ({
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
    }),
    selectors({
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
                s.personItems,
                s.groupItems,
                s.playlistItems,
                s.unifiedSearchItems,
                s.recentsLoading,
                s.personSearchResultsLoading,
                s.groupSearchResultsLoading,
                s.playlistSearchResultsLoading,
                s.unifiedSearchResultsLoading,
                s.search,
            ],
            (
                recentItems,
                personItems,
                groupItems,
                playlistItems,
                unifiedSearchItems,
                recentsLoading,
                personSearchResultsLoading,
                groupSearchResultsLoading,
                playlistSearchResultsLoading,
                unifiedSearchResultsLoading,
                search
            ): SearchCategory[] => {
                const categories: SearchCategory[] = []
                const hasSearch = search.trim() !== ''

                // Always show recents first
                if (recentItems.length > 0 || recentsLoading) {
                    categories.push({
                        key: 'recents',
                        items: recentItems,
                        isLoading: recentsLoading,
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
        },
    })),
])
