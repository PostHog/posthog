import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'

import api, { CountedPaginatedResponse } from 'lib/api'
import { featureFlagLogic } from 'lib/logic/featureFlagLogic'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { getDefaultTreeProducts, iconForType } from '~/layout/panel-layout/ProjectTree/defaultTree'
import { groupsModel } from '~/models/groupsModel'
import { FileSystemIconType, FileSystemImport } from '~/queries/schema/schema-general'
import { Group, InsightShortId, PersonType, SearchResponse, SearchableEntity } from '~/types'

import { commandBarLogic } from './commandBarLogic'
import { Tab, TabGroup, clickhouseTabs } from './constants'
import type { searchBarLogicType } from './searchBarLogicType'
import { BarStatus, GroupResult, PersonResult, SearchResult, TreeItemResult } from './types'

const DEBOUNCE_MS = 300

function calculateRank(query: string): number {
    // We know each item matches the query. To rank them
    // between the other results, we rank them higher, when the
    // query is longer.
    return query.length / (query.length + 2.0)
}

export function rankPersons(persons: PersonType[], query: string): PersonResult[] {
    const rank = calculateRank(query)
    return persons.map((person) => ({
        type: 'person',
        result_id: person.distinct_ids[0],
        extra_fields: { ...person },
        rank,
    }))
}

function rankGroups(groups: Group[], query: string): GroupResult[] {
    const rank = calculateRank(query)
    return groups.map((group) => ({
        type: 'group',
        result_id: group.group_key,
        extra_fields: { ...group },
        rank,
    }))
}

function rankProductTreeItems(treeItems: FileSystemImport[], query: string): TreeItemResult[] {
    const rank = calculateRank(query)
    return treeItems
        .filter((item) => item.path.toLowerCase().includes(query.toLowerCase()))
        .map((item) => {
            return {
                type: 'tree_item' as const,
                result_id: item.href || item.path,
                extra_fields: {
                    ...item,
                    icon: item.iconType
                        ? iconForType(item.iconType as FileSystemIconType)
                        : iconForType(item.type as FileSystemIconType),
                    description: `Category: ${item.category}`,
                },
                rank,
            }
        })
}

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    connect(() => ({
        values: [
            commandBarLogic,
            ['initialQuery', 'barStatus'],
            groupsModel,
            ['groupTypes', 'aggregationLabel'],
            featureFlagLogic,
            ['featureFlags'],
        ],
        actions: [
            commandBarLogic,
            ['hideCommandBar', 'setCommandBar', 'clearInitialQuery'],
            eventUsageLogic,
            ['reportCommandBarSearch', 'reportCommandBarSearchResultOpened'],
        ],
    })),
    actions({
        search: true,
        setSearchQuery: (query: string) => ({ query }),
        setActiveTab: (tab: Tab) => ({ tab }),
        onArrowUp: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        onArrowDown: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        openResult: (index: number) => ({ index }),
        setActiveResultIndex: (index: number) => ({ index }),
    }),
    loaders(({ values, actions }) => ({
        rawSearchResponse: [
            null as SearchResponse | null,
            {
                loadSearchResponse: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    actions.reportCommandBarSearch(values.searchQuery.length)

                    let response
                    if (values.activeTab !== Tab.All && clickhouseTabs.includes(values.activeTab)) {
                        return null
                    } else if (clickhouseTabs.includes(values.activeTab)) {
                        // prevent race conditions when switching tabs quickly
                        response = values.rawSearchResponse
                    } else if (values.activeTab === Tab.All) {
                        response = await api.search.list({ q: values.searchQuery })
                    } else if (values.activeTab === Tab.Products) {
                        return null // Products are handled separately in combinedSearchResults
                    } else {
                        response = await api.search.list({
                            q: values.searchQuery,
                            entities: [values.activeTab.toLowerCase() as SearchableEntity],
                        })
                    }

                    breakpoint()
                    return response
                },
            },
        ],
        rawPersonsResponse: [
            null as CountedPaginatedResponse<PersonType> | null,
            {
                loadPersonsResponse: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab !== Tab.All && values.activeTab !== Tab.Person) {
                        return null
                    }

                    const response = await api.persons.list({ search: values.searchQuery })
                    breakpoint()
                    return response
                },
            },
        ],
        rawGroup0Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                loadGroup0Response: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab !== Tab.All && values.activeTab !== Tab.Group0) {
                        return null
                    }

                    const response = await api.groups.list({ group_type_index: 0, search: values.searchQuery })
                    breakpoint()
                    return response
                },
            },
        ],
        rawGroup1Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                loadGroup1Response: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab !== Tab.All && values.activeTab !== Tab.Group1) {
                        return null
                    }

                    const response = await api.groups.list({ group_type_index: 1, search: values.searchQuery })
                    breakpoint()
                    return response
                },
            },
        ],
        rawGroup2Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                loadGroup2Response: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab !== Tab.All && values.activeTab !== Tab.Group2) {
                        return null
                    }

                    const response = await api.groups.list({ group_type_index: 2, search: values.searchQuery })
                    breakpoint()
                    return response
                },
            },
        ],
        rawGroup3Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                loadGroup3Response: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab !== Tab.All && values.activeTab !== Tab.Group3) {
                        return null
                    }

                    const response = await api.groups.list({ group_type_index: 3, search: values.searchQuery })
                    breakpoint()
                    return response
                },
            },
        ],
        rawGroup4Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                loadGroup4Response: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab !== Tab.All && values.activeTab !== Tab.Group4) {
                        return null
                    }

                    const response = await api.groups.list({ group_type_index: 4, search: values.searchQuery })
                    breakpoint()
                    return response
                },
            },
        ],
    })),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        rawSearchResponse: [
            null as SearchResponse | null,
            {
                search: () => null,
            },
        ],
        rawPersonsResponse: [
            null as CountedPaginatedResponse<PersonType> | null,
            {
                search: () => null,
            },
        ],
        rawGroup0Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                search: () => null,
            },
        ],
        rawGroup1Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                search: () => null,
            },
        ],
        rawGroup2Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                search: () => null,
            },
        ],
        rawGroup3Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                search: () => null,
            },
        ],
        rawGroup4Response: [
            null as CountedPaginatedResponse<Group> | null,
            {
                search: () => null,
            },
        ],
        activeResultIndex: [
            0,
            {
                setSearchQuery: () => 0,
                setActiveTab: () => 0,
                openResult: () => 0,
                onArrowUp: (_, { activeIndex, maxIndex }) => (activeIndex > 0 ? activeIndex - 1 : maxIndex),
                onArrowDown: (_, { activeIndex, maxIndex }) => (activeIndex < maxIndex ? activeIndex + 1 : 0),
                setActiveResultIndex: (_, { index }) => index,
            },
        ],
        activeTab: [
            Tab.All as Tab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
    }),
    selectors({
        combinedSearchResults: [
            (s) => [
                s.rawSearchResponse,
                s.rawPersonsResponse,
                s.rawGroup0Response,
                s.rawGroup1Response,
                s.rawGroup2Response,
                s.rawGroup3Response,
                s.rawGroup4Response,
                s.searchQuery,
                s.activeTab,
                s.featureFlags,
            ],
            (
                searchResponse,
                personsResponse,
                group0Response,
                group1Response,
                group2Response,
                group3Response,
                group4Response,
                query,
                activeTab,
                featureFlags
            ) => {
                const results = []

                // Add regular search results (not for Products tab)
                if (activeTab !== Tab.Products && searchResponse) {
                    results.push(...searchResponse.results)
                }

                // Add persons results
                if (personsResponse) {
                    results.push(...rankPersons(personsResponse.results, query))
                }

                // Add group results
                if (group0Response) {
                    results.push(...rankGroups(group0Response.results, query))
                }
                if (group1Response) {
                    results.push(...rankGroups(group1Response.results, query))
                }
                if (group2Response) {
                    results.push(...rankGroups(group2Response.results, query))
                }
                if (group3Response) {
                    results.push(...rankGroups(group3Response.results, query))
                }
                if (group4Response) {
                    results.push(...rankGroups(group4Response.results, query))
                }

                if (activeTab === Tab.All || activeTab === Tab.Products) {
                    const productTreeItems = getDefaultTreeProducts()

                    // Filter out items that don't have the correct feature flag
                    const filteredTreeItems = productTreeItems.filter((item) => {
                        if (item.flag) {
                            return !!featureFlags[item.flag as keyof typeof featureFlags]
                        }
                        return true
                    })

                    const treeResults = query
                        ? rankProductTreeItems(filteredTreeItems, query)
                        : rankProductTreeItems(filteredTreeItems, '')
                    results.push(...treeResults)
                }

                return results.sort((a, b) => (a.rank && b.rank ? a.rank - b.rank : 1))
            },
        ],
        combinedSearchLoading: [
            (s) => [
                s.rawSearchResponseLoading,
                s.rawPersonsResponseLoading,
                s.rawGroup0ResponseLoading,
                s.rawGroup1ResponseLoading,
                s.rawGroup2ResponseLoading,
                s.rawGroup3ResponseLoading,
                s.rawGroup4ResponseLoading,
                s.activeTab,
            ],
            (
                searchLoading: boolean,
                personsLoading: boolean,
                group0Loading: boolean,
                group1Loading: boolean,
                group2Loading: boolean,
                group3Loading: boolean,
                group4Loading: boolean,
                activeTab: Tab
            ) => {
                // For individual tabs, only check the relevant loading state
                if (activeTab === Tab.Person) {
                    return personsLoading
                }
                if (activeTab === Tab.Group0) {
                    return group0Loading
                }
                if (activeTab === Tab.Group1) {
                    return group1Loading
                }
                if (activeTab === Tab.Group2) {
                    return group2Loading
                }
                if (activeTab === Tab.Group3) {
                    return group3Loading
                }
                if (activeTab === Tab.Group4) {
                    return group4Loading
                }
                if (activeTab !== Tab.All && activeTab !== Tab.Products) {
                    return searchLoading
                }

                // For "All" tab, only show loading if the primary search is loading
                // This allows other results to show while slow group searches are still running
                return searchLoading
            },
        ],
        anySearchLoading: [
            (s) => [
                s.rawSearchResponseLoading,
                s.rawPersonsResponseLoading,
                s.rawGroup0ResponseLoading,
                s.rawGroup1ResponseLoading,
                s.rawGroup2ResponseLoading,
                s.rawGroup3ResponseLoading,
                s.rawGroup4ResponseLoading,
            ],
            (
                searchLoading,
                personsLoading,
                group0Loading,
                group1Loading,
                group2Loading,
                group3Loading,
                group4Loading
            ) =>
                searchLoading ||
                personsLoading ||
                group0Loading ||
                group1Loading ||
                group2Loading ||
                group3Loading ||
                group4Loading,
        ],
        tabsForGroups: [
            (s) => [s.groupTypes],
            (groupTypes): Tab[] => {
                return Array.from(groupTypes.values()).map(({ group_type_index }) => `group_${group_type_index}` as Tab)
            },
        ],
        tabsGrouped: [
            (s) => [s.tabsForGroups],
            (tabsForGroups): Record<TabGroup, Tab[]> => {
                return {
                    all: [Tab.All],
                    event_data: [Tab.EventDefinition, Tab.Action, Tab.Person, Tab.Cohort, ...tabsForGroups],
                    products: [Tab.Products],
                    posthog: [Tab.Insight, Tab.Dashboard, Tab.Notebook, Tab.Experiment, Tab.FeatureFlag, Tab.Survey],
                }
            },
        ],
        tabs: [
            (s) => [s.tabsGrouped],
            (tabsGrouped): Tab[] => {
                return Object.values(tabsGrouped).reduce((acc, val) => acc.concat(val), [])
            },
        ],
        tabsCount: [(s) => [s.tabsCountMemoized], (tabsCountMemoized) => tabsCountMemoized[0]],
        tabsCountMemoized: [
            (s) => [
                s.rawSearchResponse,
                s.rawPersonsResponse,
                s.rawGroup0Response,
                s.rawGroup1Response,
                s.rawGroup2Response,
                s.rawGroup3Response,
                s.rawGroup4Response,
                s.searchQuery,
                s.activeTab,
                s.featureFlags,
            ],
            (
                searchResponse,
                personsResponse,
                group0Response,
                group1Response,
                group2Response,
                group3Response,
                group4Response,
                searchQuery,
                activeTab,
                featureFlags
            ): [Record<Tab, string | null>, string] => {
                /** :TRICKY: We need to pull in the searchQuery to memoize the counts. */

                const counts: Record<string, string | null> = {}

                Object.values(Tab).forEach((tab) => {
                    counts[tab] = searchResponse?.counts[tab as SearchableEntity]?.toString() || null
                })

                // Handle Products tab count
                if (activeTab === Tab.Products || activeTab === Tab.All) {
                    const treeItems = getDefaultTreeProducts()
                    const flagFilteredItems = treeItems.filter((item) => {
                        if (item.flag) {
                            return !!featureFlags[item.flag as keyof typeof featureFlags]
                        }
                        return true
                    })

                    const filteredItems = searchQuery
                        ? flagFilteredItems.filter((item) =>
                              item.path.toLowerCase().includes(searchQuery.toLowerCase())
                          )
                        : flagFilteredItems

                    counts[Tab.Products] = filteredItems.length.toString()
                }

                const clickhouseTabsResults: [string, unknown[] | undefined][] = [
                    [Tab.Person, personsResponse?.results],
                    [Tab.Group0, group0Response?.results],
                    [Tab.Group1, group1Response?.results],
                    [Tab.Group2, group2Response?.results],
                    [Tab.Group3, group3Response?.results],
                    [Tab.Group4, group4Response?.results],
                ]
                clickhouseTabsResults.forEach(([tab, results]) => {
                    if (results !== undefined) {
                        counts[tab] = results.length === 100 ? '100+' : results.length.toString()
                    }
                })

                return [counts as Record<Tab, string | null>, searchQuery]
            },
            {
                resultEqualityCheck: (prev, next) => {
                    const [prevCounts, prevQuery] = prev
                    const [nextCounts, nextQuery] = next

                    if (prevQuery !== nextQuery) {
                        return false
                    }

                    const prevNulls = Object.values(prevCounts).filter((v) => v === null).length
                    const nextNulls = Object.values(nextCounts).filter((v) => v === null).length

                    if (nextNulls !== prevNulls) {
                        return false
                    }

                    return true
                },
            },
        ],
        tabsLoading: [
            (s) => [s.rawSearchResponseLoading, s.rawPersonsResponseLoading, s.activeTab],
            (searchLoading, personsLoading, activeTab): Tab[] => {
                const tabs: Tab[] = []

                if (searchLoading) {
                    if (activeTab === Tab.All) {
                        tabs.push(...Object.values(Tab).filter((tab) => ![Tab.All, Tab.Person].includes(tab)))
                    } else {
                        tabs.push(activeTab)
                    }
                }

                if (personsLoading) {
                    tabs.push(Tab.Person)
                }

                return tabs
            },
        ],
        maxIndex: [
            (s) => [s.combinedSearchResults],
            (combinedResults) => (combinedResults ? combinedResults.length - 1 : 0),
        ],
    }),
    listeners(({ values, actions }) => ({
        setSearchQuery: actions.search,
        setActiveTab: actions.search,
        search: (_) => {
            // postgres search
            actions.loadSearchResponse(_)

            // clickhouse persons
            actions.loadPersonsResponse(_)

            // clickhouse groups
            actions.loadGroup0Response(_)
            actions.loadGroup1Response(_)
            actions.loadGroup2Response(_)
            actions.loadGroup3Response(_)
            actions.loadGroup4Response(_)
        },
        openResult: ({ index }) => {
            const result = values.combinedSearchResults![index]
            router.actions.push(urlForResult(result))
            actions.hideCommandBar()
            actions.reportCommandBarSearchResultOpened(result.type)
        },
    })),
    subscriptions(({ values, actions }) => ({
        barStatus: (value, oldvalue) => {
            if (value !== BarStatus.SHOW_SEARCH || oldvalue === BarStatus.SHOW_SEARCH) {
                return
            }

            if (values.initialQuery !== null) {
                // set default query from url
                actions.setSearchQuery(values.initialQuery)
                actions.clearInitialQuery()
            } else {
                // load initial results
                actions.setSearchQuery('')
                actions.clearInitialQuery()
            }
        },
    })),
    afterMount(({ actions, values, cache }) => {
        // register keyboard shortcuts
        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Enter') {
                // open result
                event.preventDefault()
                actions.openResult(values.activeResultIndex)
            } else if (event.key === 'ArrowDown') {
                // navigate to next result
                event.preventDefault()
                actions.onArrowDown(values.activeResultIndex, values.maxIndex)
            } else if (event.key === 'ArrowUp') {
                // navigate to previous result
                event.preventDefault()
                actions.onArrowUp(values.activeResultIndex, values.maxIndex)
            } else if (event.key === 'Escape' && event.repeat === false) {
                // hide command bar
                actions.hideCommandBar()
            } else if (event.key === '>') {
                const { value, selectionStart, selectionEnd } = event.target as HTMLInputElement
                if (
                    values.searchQuery.length === 0 ||
                    (selectionStart !== null &&
                        selectionEnd !== null &&
                        (value.substring(0, selectionStart) + value.substring(selectionEnd)).length === 0)
                ) {
                    // transition to actions when entering '>' with empty input, or when replacing the whole input
                    event.preventDefault()
                    actions.setCommandBar(BarStatus.SHOW_ACTIONS)
                }
            } else if (event.key === 'Tab') {
                event.preventDefault()

                const currentIndex = values.tabs.findIndex((tab) => tab === values.activeTab)
                if (event.shiftKey) {
                    const prevIndex = currentIndex === 0 ? values.tabs.length - 1 : currentIndex - 1
                    actions.setActiveTab(values.tabs[prevIndex])
                } else {
                    const nextIndex = currentIndex === values.tabs.length - 1 ? 0 : currentIndex + 1
                    actions.setActiveTab(values.tabs[nextIndex])
                }
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ cache }) => {
        // unregister keyboard shortcuts
        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])

export const urlForResult = (result: SearchResult): string => {
    switch (result.type) {
        case 'action':
            return urls.action(result.result_id)
        case 'cohort':
            return urls.cohort(result.result_id)
        case 'dashboard':
            return urls.dashboard(result.result_id)
        case 'event_definition':
            return urls.eventDefinition(result.result_id)
        case 'experiment':
            return urls.experiment(result.result_id)
        case 'feature_flag':
            return urls.featureFlag(result.result_id)
        case 'group':
            return urls.group(result.extra_fields.group_type_index, result.result_id)
        case 'insight':
            return urls.insightView(result.result_id as InsightShortId)
        case 'notebook':
            return urls.notebook(result.result_id)
        case 'person':
            return urls.personByDistinctId(result.result_id)
        case 'survey':
            return urls.survey(result.result_id)
        case 'tree_item':
            return result.extra_fields.href || result.result_id
        default:
            // @ts-expect-error
            throw new Error(`No action for type '${result?.type}' defined.`)
    }
}
