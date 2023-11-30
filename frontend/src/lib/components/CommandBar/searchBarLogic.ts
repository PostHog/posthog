import { actions, afterMount, beforeUnmount, connect, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'
import api, { CountedPaginatedResponse } from 'lib/api'
import { urls } from 'scenes/urls'

import { InsightShortId, PersonType, SearchableEntity, SearchResponse } from '~/types'

import { commandBarLogic } from './commandBarLogic'
import { Tab } from './constants'
import type { searchBarLogicType } from './searchBarLogicType'
import { BarStatus, PersonResult, SearchResult } from './types'

const DEBOUNCE_MS = 300

function rankPersons(persons: PersonType[], query: string): PersonResult[] {
    // We know each person matches the query. To rank them
    // between the other results, we rank them higher, when the
    // query is longer.
    const personsRank = query.length / (query.length + 2.0)
    return persons.map((person) => ({
        type: 'person',
        result_id: person.distinct_ids[0],
        extra_fields: { ...person },
        rank: personsRank,
    }))
}

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    connect({
        actions: [commandBarLogic, ['hideCommandBar', 'setCommandBar']],
    }),
    actions({
        search: true,
        setSearchQuery: (query: string) => ({ query }),
        setActiveTab: (tab: Tab) => ({ tab }),
        onArrowUp: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        onArrowDown: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        onMouseEnterResult: (index: number) => ({ index }),
        onMouseLeaveResult: true,
        setIsAutoScrolling: (scrolling: boolean) => ({ scrolling }),
        openResult: (index: number) => ({ index }),
    }),
    loaders(({ values }) => ({
        rawSearchResponse: [
            null as SearchResponse | null,
            {
                loadSearchResponse: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    if (values.activeTab === Tab.All) {
                        return await api.search.list({ q: values.searchQuery })
                    } else {
                        return await api.search.list({
                            q: values.searchQuery,
                            entities: [values.activeTab.toLowerCase() as SearchableEntity],
                        })
                    }
                },
            },
        ],
        rawPersonsResponse: [
            null as CountedPaginatedResponse<PersonType> | null,
            {
                loadPersonsResponse: async (_, breakpoint) => {
                    await breakpoint(DEBOUNCE_MS)

                    return await api.persons.list({ search: values.searchQuery })
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
        keyboardResultIndex: [
            0,
            {
                setSearchQuery: () => 0,
                setActiveTab: () => 0,
                openResult: () => 0,
                onArrowUp: (_, { activeIndex, maxIndex }) => (activeIndex > 0 ? activeIndex - 1 : maxIndex),
                onArrowDown: (_, { activeIndex, maxIndex }) => (activeIndex < maxIndex ? activeIndex + 1 : 0),
            },
        ],
        hoverResultIndex: [
            null as number | null,
            {
                setSearchQuery: () => null,
                setActiveTab: () => null,
                onMouseEnterResult: (_, { index }) => index,
                onMouseLeaveResult: () => null,
                onArrowUp: () => null,
                onArrowDown: () => null,
            },
        ],
        activeTab: [
            Tab.All as Tab,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        isAutoScrolling: [false, { setIsAutoScrolling: (_, { scrolling }) => scrolling }],
    }),
    selectors({
        combinedSearchResults: [
            (s) => [s.rawSearchResponse, s.rawPersonsResponse, s.searchQuery],
            (searchResponse, personsResponse, query) => {
                if (!searchResponse && !personsResponse) {
                    return null
                }

                return [
                    ...(searchResponse ? searchResponse.results : []),
                    ...(personsResponse ? rankPersons(personsResponse.results, query) : []),
                ].sort((a, b) => (a.rank && b.rank ? a.rank - b.rank : 1))
            },
        ],
        combinedSearchLoading: [
            (s) => [s.rawSearchResponseLoading, s.rawPersonsResponseLoading],
            (searchLoading, personsLoading) => searchLoading && personsLoading,
        ],
        tabsCount: [
            (s) => [s.rawSearchResponse, s.rawPersonsResponse],
            (searchResponse, personsResponse): Record<Tab, string | null> => {
                const counts = {}
                const personsResults = personsResponse?.results

                Object.values(Tab).forEach((tab) => {
                    counts[tab] = searchResponse?.counts[tab]?.toString() || null
                })

                if (personsResults !== undefined) {
                    counts[Tab.Person] = personsResults.length === 100 ? '>=100' : personsResults.length.toString()
                }

                return counts as Record<Tab, string | null>
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
        activeResultIndex: [
            (s) => [s.keyboardResultIndex, s.hoverResultIndex],
            (keyboardResultIndex: number, hoverResultIndex: number | null) => hoverResultIndex || keyboardResultIndex,
        ],
    }),
    listeners(({ values, actions }) => ({
        setSearchQuery: actions.search,
        setActiveTab: actions.search,
        search: (_) => {
            if (values.activeTab === Tab.All || values.activeTab !== Tab.Person) {
                actions.loadSearchResponse(_)
            }
            if (values.activeTab === Tab.All || values.activeTab === Tab.Person) {
                actions.loadPersonsResponse(_)
            }
        },
        openResult: ({ index }) => {
            const result = values.combinedSearchResults![index]
            router.actions.push(urlForResult(result))
            actions.hideCommandBar()
        },
    })),
    afterMount(({ actions, values, cache }) => {
        // load initial results
        actions.setSearchQuery('')

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
                const tabs = Object.values(Tab)
                const currentIndex = tabs.findIndex((tab) => tab === values.activeTab)
                if (event.shiftKey) {
                    const prevIndex = currentIndex === 0 ? tabs.length - 1 : currentIndex - 1
                    actions.setActiveTab(tabs[prevIndex])
                } else {
                    const nextIndex = currentIndex === tabs.length - 1 ? 0 : currentIndex + 1
                    actions.setActiveTab(tabs[nextIndex])
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
        case 'insight':
            return urls.insightView(result.result_id as InsightShortId)
        case 'notebook':
            return urls.notebook(result.result_id)
        case 'person':
            return urls.personByDistinctId(result.result_id)
        default:
            // @ts-expect-error
            throw new Error(`No action for type '${result?.type}' defined.`)
    }
}
