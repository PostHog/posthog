import { kea, path, actions, reducers, selectors, listeners, connect, afterMount, beforeUnmount } from 'kea'
import { loaders } from 'kea-loaders'
import { router } from 'kea-router'

import api from 'lib/api'
import { urls } from 'scenes/urls'
import { InsightShortId } from '~/types'
import { commandBarLogic } from './commandBarLogic'

import type { searchBarLogicType } from './searchBarLogicType'
import { BarStatus, ResultTypeWithAll, SearchResponse, SearchResult } from './types'

export const searchBarLogic = kea<searchBarLogicType>([
    path(['lib', 'components', 'CommandBar', 'searchBarLogic']),
    connect({
        actions: [commandBarLogic, ['hideCommandBar', 'setCommandBar']],
    }),
    actions({
        setSearchQuery: (query: string) => ({ query }),
        setActiveTab: (tab: ResultTypeWithAll) => ({ tab }),
        onArrowUp: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        onArrowDown: (activeIndex: number, maxIndex: number) => ({ activeIndex, maxIndex }),
        onMouseEnterResult: (index: number) => ({ index }),
        onMouseLeaveResult: true,
        setIsAutoScrolling: (scrolling: boolean) => ({ scrolling }),
        openResult: (index: number) => ({ index }),
    }),
    loaders(({ values }) => ({
        searchResponse: [
            null as SearchResponse | null,
            {
                loadSearchResponse: async (_, breakpoint) => {
                    await breakpoint(300)
                    if (values.activeTab === 'all') {
                        return await api.get(`api/projects/@current/search?q=${values.searchQuery}`)
                    } else {
                        return await api.get(
                            `api/projects/@current/search?q=${values.searchQuery}&entities=${values.activeTab}`
                        )
                    }
                },
            },
        ],
    })),
    reducers({
        searchQuery: ['', { setSearchQuery: (_, { query }) => query }],
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
            'all' as ResultTypeWithAll,
            {
                setActiveTab: (_, { tab }) => tab,
            },
        ],
        isAutoScrolling: [false, { setIsAutoScrolling: (_, { scrolling }) => scrolling }],
    }),
    selectors({
        searchResults: [(s) => [s.searchResponse], (searchResponse) => searchResponse?.results],
        searchCounts: [(s) => [s.searchResponse], (searchResponse) => searchResponse?.counts],
        filterSearchResults: [
            (s) => [s.searchResults, s.activeTab],
            (searchResults, activeTab) => {
                if (activeTab === 'all') {
                    return searchResults
                }
                return searchResults?.filter((r) => r.type === activeTab)
            },
        ],
        maxIndex: [(s) => [s.filterSearchResults], (searchResults) => (searchResults ? searchResults.length - 1 : 0)],
        activeResultIndex: [
            (s) => [s.keyboardResultIndex, s.hoverResultIndex],
            (keyboardResultIndex: number, hoverResultIndex: number | null) => hoverResultIndex || keyboardResultIndex,
        ],
    }),
    listeners(({ values, actions }) => ({
        openResult: ({ index }) => {
            const result = values.searchResults![index]
            router.actions.push(urlForResult(result))
            actions.hideCommandBar()
        },
        setSearchQuery: actions.loadSearchResponse,
        setActiveTab: actions.loadSearchResponse,
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
            } else if (event.key === 'Escape') {
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
        case 'experiment':
            return urls.experiment(result.result_id)
        case 'feature_flag':
            return urls.featureFlag(result.result_id)
        case 'insight':
            return urls.insightView(result.result_id as InsightShortId)
        case 'notebook':
            return urls.notebook(result.result_id)
        default:
            throw new Error(`No action for type '${result.type}' defined.`)
    }
}
