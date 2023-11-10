import { kea, path, actions, reducers, selectors, listeners, connect, afterMount, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'
import { commandPaletteLogic } from '../CommandPalette/commandPaletteLogic'
import { commandBarLogic } from './commandBarLogic'

import { ResultTypeWithAll, SearchResponse, SearchResult } from './types'

import type { actionBarLogicType } from './actionBarLogicType'

export const actionBarLogic = kea<actionBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'actionBarLogic']),
    connect({
        actions: [
            commandBarLogic,
            ['hideCommandBar'],
            commandPaletteLogic,
            ['showPalette', 'hidePalette', 'setInput', 'executeResult', 'onArrowUp', 'onArrowDown'],
        ],
        values: [
            commandPaletteLogic,
            [
                'input',
                'activeResultIndex',
                'commandRegistrations',
                'commandSearchResults',
                'commandSearchResultsGrouped',
                'activeFlow',
                'isSqueak',
            ],
        ],
    }),
    actions({
        // onArrowUp: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        // onArrowDown: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        // onMouseEnterResult: (index: number) => ({ index }),
        // onMouseLeaveResult: true,
        // setScrolling: (scrolling: boolean) => ({ scrolling }),
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
        // keyboardResultIndex: [
        //     0,
        //     {
        //         onArrowUp: (_, { activeIndex, maxIndex }) => (activeIndex > 0 ? activeIndex - 1 : maxIndex),
        //         onArrowDown: (_, { activeIndex, maxIndex }) => (activeIndex < maxIndex ? activeIndex + 1 : 0),
        //     },
        // ],
        // hoverResultIndex: [
        //     null as number | null,
        //     {
        //         onMouseEnterResult: (_, { index }) => index,
        //         onMouseLeaveResult: () => null,
        //         onArrowUp: () => null,
        //         onArrowDown: () => null,
        //     },
        // ],
        // scrolling: [false, { setScrolling: (_, { scrolling }) => scrolling }],
    }),
    selectors({
        // searchResults: [
        //     (s) => [s.commandSearchResults],
        //     (commandSearchResults) => commandSearchResults.map((result, index) => ({ ...result, index })),
        // ],
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
        hidePalette: () => {
            actions.hideCommandBar()
        },
    })),
    afterMount(({ actions, values, cache }) => {
        // actions.setSearchQuery('')
        actions.showPalette()

        cache.onKeyDown = (event: KeyboardEvent) => {
            if (event.key === 'Enter' && values.commandSearchResults.length) {
                const result = values.commandSearchResults[values.activeResultIndex]
                const isExecutable = !!result.executor
                if (isExecutable) {
                    actions.executeResult(result)
                }
            } else if (event.key === 'ArrowDown') {
                event.preventDefault()
                actions.onArrowDown(values.commandSearchResults.length - 1)
            } else if (event.key === 'ArrowUp') {
                event.preventDefault()
                actions.onArrowUp()
            }
        }
        window.addEventListener('keydown', cache.onKeyDown)
    }),
    beforeUnmount(({ actions, cache }) => {
        actions.hidePalette()

        window.removeEventListener('keydown', cache.onKeyDown)
    }),
])
