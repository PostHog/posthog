import { kea, path, actions, reducers, selectors, listeners, connect, afterMount, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'
import { commandPaletteLogic } from '../CommandPalette/commandPaletteLogic'
import { commandBarLogic } from './commandBarLogic'
import { searchBarLogic } from './searchBarLogic'

import { ResultTypeWithAll, SearchResponse, SearchResult } from './types'

export const actionBarLogic = kea([
    path(['lib', 'components', 'CommandBar', 'actionBarLogic']),
    connect({
        actions: [commandBarLogic, ['hideCommandBar'], commandPaletteLogic, ['showPalette', 'hidePalette', 'setInput']],
        values: [commandPaletteLogic, ['commandRegistrations', 'commandSearchResults', 'commandSearchResultsGrouped']],
    }),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        // setActiveTab: (tab: ResultTypeWithAll) => ({ tab }),
        // onArrowUp: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        // onArrowDown: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        // onMouseEnterResult: (index: number) => ({ index }),
        // onMouseLeaveResult: true,
        // setScrolling: (scrolling: boolean) => ({ scrolling }),
        // openResult: (index: number) => ({ index }),
    }),
    loaders({
        searchResponse: [
            null as SearchResponse | null,
            {
                setSearchQuery: async ({ query }) => {
                    return await api.get(`api/projects/@current/search?q=${query}`)
                },
            },
        ],
    }),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
        // keyboardResultIndex: [
        //     0,
        //     {
        //         setSearchQuery: () => 0,
        //         setActiveTab: () => 0,
        //         openResult: () => 0,
        //         onArrowUp: (_, { activeIndex, maxIndex }) => (activeIndex > 0 ? activeIndex - 1 : maxIndex),
        //         onArrowDown: (_, { activeIndex, maxIndex }) => (activeIndex < maxIndex ? activeIndex + 1 : 0),
        //     },
        // ],
        // hoverResultIndex: [
        //     null as number | null,
        //     {
        //         setSearchQuery: () => null,
        //         setActiveTab: () => null,
        //         onMouseEnterResult: (_, { index }) => index,
        //         onMouseLeaveResult: () => null,
        //         onArrowUp: () => null,
        //         onArrowDown: () => null,
        //     },
        // ],
        // activeTab: [
        //     'all' as ResultTypeWithAll,
        //     {
        //         setActiveTab: (_, { tab }) => tab,
        //     },
        // ],
        // scrolling: [false, { setScrolling: (_, { scrolling }) => scrolling }],
    }),
    selectors({
        searchResults: [
            (s) => [s.commandSearchResults],
            (commandSearchResults) => commandSearchResults.map((result, index) => ({ ...result, index })),
        ],
        //     searchCounts: [(s) => [s.searchResponse], (searchResponse) => searchResponse?.counts],
        //     filterSearchResults: [
        //         (s) => [s.searchResults, s.activeTab],
        //         (searchResults, activeTab) => {
        //             if (activeTab === 'all') {
        //                 return searchResults
        //             }
        //             return searchResults?.filter((r) => r.type === activeTab)
        //         },
        //     ],
        //     maxIndex: [(s) => [s.filterSearchResults], (searchResults) => (searchResults ? searchResults.length - 1 : 0)],
        //     activeResultIndex: [
        //         (s) => [s.keyboardResultIndex, s.hoverResultIndex],
        //         (keyboardResultIndex: number, hoverResultIndex: number | null) => hoverResultIndex || keyboardResultIndex,
        //     ],
    }),
    listeners(({ values, actions }) => ({
        setSearchQuery: ({ query }) => {
            actions.setInput(query)
        },
        // openResult: ({ index }) => {
        //     // eslint-disable-next-line @typescript-eslint/no-non-null-assertion
        //     const result = values.searchResults![index]
        //     router.actions.push(urlForResult(result))
        //     actions.hideCommandBar()
        // },
    })),
    afterMount(({ actions }) => {
        actions.setSearchQuery('')
        actions.showPalette()
    }),
    beforeUnmount(({ actions }) => {
        actions.hidePalette()
    }),
])
