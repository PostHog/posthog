import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import { subscriptions } from 'kea-subscriptions'
import api, { CountedPaginatedResponse } from 'lib/api'
import { eventUsageLogic } from 'lib/utils/eventUsageLogic'
import { urls } from 'scenes/urls'

import { groupsModel } from '~/models/groupsModel'
import { Group, InsightShortId, PersonType, SearchableEntity, SearchResponse } from '~/types'

import { commandBarLogic } from './commandBarLogic'
import { clickhouseTabs, Tab, TabGroup } from './constants'
import type { searchBarLogicType } from './searchBarLogicType'
import { BarStatus, GroupResult, PersonResult, SearchResult } from './types'

const DEBOUNCE_MS = 300

function calculateRank(query: string): number {
    // We know each item matches the query. To rank them
    // between the other results, we rank them higher, when the
    // query is longer.
    return query.length / (query.length + 2.0)
}

function rankPersons(persons: PersonType[], query: string): PersonResult[] {
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

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    connect({
        values: [commandBarLogic, ['initialQuery', 'barStatus'], groupsModel, ['groupTypes', 'aggregationLabel']],
        actions: [
            commandBarLogic,
            ['hideCommandBar', 'setCommandBar', 'clearInitialQuery'],
            eventUsageLogic,
            ['reportCommandBarSearch', 'reportCommandBarSearchResultOpened'],
        ],
    }),
    actions({
        search: true,
        setSearchQuery: (query: string) => ({ query }),
        setActiveTab: (tab: Tab) => ({ tab }),
        onArrowUp: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        onArrowDown: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        openResult: (index: number) => ({ index }),
    }),
    loaders(({ values, actions }) => ({
        rawSearchResponse: [
            null as SearchResponse | null,
            {
                loadSearchResponse: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    actions.reportCommandBarSearch(values.searchQuery.length)

                    let response
                    if (clickhouseTabs.includes(values.activeTab)) {
                        // prevent race conditions when switching tabs quickly
                        response = values.rawSearchResponse
                    } else if (values.activeTab === Tab.All) {
                        response = await api.search.list({ q: values.searchQuery })
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
            ],
            (
                searchResponse,
                personsResponse,
                group0Response,
                group1Response,
                group2Response,
                group3Response,
                group4Response,
                query
            ) => {
                if (
                    !searchResponse &&
                    !personsResponse &&
                    !group0Response &&
                    !group1Response &&
                    !group2Response &&
                    !group3Response &&
                    !group4Response
                ) {
                    return null
                }

                return [
                    ...(searchResponse ? searchResponse.results : []),
                    ...(personsResponse ? rankPersons(personsResponse.results, query) : []),
                    ...(group0Response ? rankGroups(group0Response.results, query) : []),
                    ...(group1Response ? rankGroups(group1Response.results, query) : []),
                    ...(group2Response ? rankGroups(group2Response.results, query) : []),
                    ...(group3Response ? rankGroups(group3Response.results, query) : []),
                    ...(group4Response ? rankGroups(group4Response.results, query) : []),
                ].sort((a, b) => (a.rank && b.rank ? a.rank - b.rank : 1))
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
                searchLoading &&
                personsLoading &&
                group0Loading &&
                group1Loading &&
                group2Loading &&
                group3Loading &&
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
            ],
            (
                searchResponse,
                personsResponse,
                group0Response,
                group1Response,
                group2Response,
                group3Response,
                group4Response,
                searchQuery
            ): [Record<Tab, string | null>, string] => {
                /** :TRICKY: We need to pull in the searchQuery to memoize the counts. */

                const counts = {}

                Object.values(Tab).forEach((tab) => {
                    counts[tab] = searchResponse?.counts[tab]?.toString() || null
                })

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
            if (values.activeTab === Tab.All || !clickhouseTabs.includes(values.activeTab)) {
                actions.loadSearchResponse(_)
            }

            // clickhouse persons
            if (values.activeTab === Tab.All || values.activeTab === Tab.Person) {
                actions.loadPersonsResponse(_)
            }

            // clickhouse groups
            if (values.activeTab === Tab.All) {
                for (const type of Array.from(values.groupTypes.values())) {
                    actions[`loadGroup${type.group_type_index}Response`](_)
                }
            } else if (values.activeTab.startsWith('group_')) {
                actions[`loadGroup${values.activeTab.split('_')[1]}Response`](_)
            }
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
        default:
            // @ts-expect-error
            throw new Error(`No action for type '${result?.type}' defined.`)
    }
}
