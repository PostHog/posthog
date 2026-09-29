import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { DataModelingEdge, DataModelingNode, DataModelingNodeType } from '~/types'

import { NodeTypeEnumApi } from '../generated/api.schemas'
import { lineageDataLogic } from './lineageDataLogic'
import {
    ParsedLineageSearch,
    edgesWithinNodes,
    matchNodesByName,
    orderedNodesForLineageSearch,
    parseLineageSearch,
} from './lineageSearch'

export const LINEAGE_FILTER_TYPES: DataModelingNodeType[] = Object.values(NodeTypeEnumApi)

type SearchResultFocusTrigger = 'keyboard' | 'click' | 'previous' | 'next'

export interface SearchFocusRequest {
    nodeId: string
    requestId: number
}

export interface modelsLineageLogicValues {
    nodes: DataModelingNode[] // lineageDataLogic
    nodesLoading: boolean // lineageDataLogic
    edges: DataModelingEdge[] // lineageDataLogic
    edgesLoading: boolean // lineageDataLogic
    searchTerm: string
    debouncedSearchTerm: string
    typeFilter: DataModelingNodeType[]
    legendCollapsed: boolean
    selectedSearchResultId: string | null
    searchFocusRequest: SearchFocusRequest | null
    parsedSearchTerm: ParsedLineageSearch
    parsedSearch: ParsedLineageSearch
    lineageSearchAnchor: DataModelingNode | null
    orderedLineageNodes: DataModelingNode[] | null
    searchResults: DataModelingNode[]
    showSearchResults: boolean
    selectedSearchResult: DataModelingNode | null
    searchResultAnnouncement: string
    highlightedNodeIds: Set<string>
    focusNodeIds: Set<string> | null
    visibleNodes: DataModelingNode[]
    visibleEdges: DataModelingEdge[]
    isFiltered: boolean
}

export interface modelsLineageLogicActions {
    setSearchTerm: (searchTerm: string) => { searchTerm: string }
    setDebouncedSearchTerm: (searchTerm: string) => { searchTerm: string }
    setTypeFilter: (typeFilter: DataModelingNodeType[]) => { typeFilter: DataModelingNodeType[] }
    selectSearchResult: (nodeId: string) => { nodeId: string }
    moveSearchResult: (
        direction: 'previous' | 'next',
        focus: boolean
    ) => {
        direction: 'previous' | 'next'
        focus: boolean
    }
    focusSearchResult: (
        nodeId: string,
        trigger: SearchResultFocusTrigger
    ) => {
        nodeId: string
        trigger: SearchResultFocusTrigger
    }
    toggleLegendCollapsed: () => Record<string, never>
    resetFilters: () => Record<string, never>
}

export type modelsLineageLogicType = MakeLogicType<modelsLineageLogicValues, modelsLineageLogicActions>

export const modelsLineageLogic = kea<modelsLineageLogicType>([
    path(['scenes', 'models', 'modelsLineageLogic']),
    connect(() => ({
        values: [lineageDataLogic, ['nodes', 'nodesLoading', 'edges', 'edgesLoading']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setDebouncedSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setTypeFilter: (typeFilter: DataModelingNodeType[]) => ({ typeFilter }),
        selectSearchResult: (nodeId: string) => ({ nodeId }),
        moveSearchResult: (direction: 'previous' | 'next', focus: boolean) => ({ direction, focus }),
        focusSearchResult: (nodeId: string, trigger: SearchResultFocusTrigger) => ({ nodeId, trigger }),
        toggleLegendCollapsed: true,
        resetFilters: true,
    }),
    reducers({
        searchTerm: [
            '',
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
                resetFilters: () => '',
            },
        ],
        debouncedSearchTerm: [
            '',
            {
                setDebouncedSearchTerm: (_, { searchTerm }) => searchTerm,
                resetFilters: () => '',
            },
        ],
        typeFilter: [
            LINEAGE_FILTER_TYPES,
            {
                setTypeFilter: (_, { typeFilter }) => typeFilter,
                resetFilters: () => LINEAGE_FILTER_TYPES,
            },
        ],
        legendCollapsed: [
            false,
            {
                toggleLegendCollapsed: (collapsed) => !collapsed,
            },
        ],
        selectedSearchResultId: [
            null as string | null,
            {
                selectSearchResult: (_, { nodeId }) => nodeId,
                focusSearchResult: (_, { nodeId }) => nodeId,
                setSearchTerm: () => null,
                setTypeFilter: () => null,
                resetFilters: () => null,
            },
        ],
        searchFocusRequest: [
            null as SearchFocusRequest | null,
            {
                focusSearchResult: (request, { nodeId }) => ({ nodeId, requestId: (request?.requestId ?? 0) + 1 }),
                selectSearchResult: () => null,
                setSearchTerm: () => null,
                setTypeFilter: () => null,
                resetFilters: () => null,
            },
        ],
    }),
    listeners(({ actions, values }) => ({
        // Every keystroke would otherwise prune the graph and start a fresh ELK layout.
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            await breakpoint(250)
            actions.setDebouncedSearchTerm(searchTerm)
        },
        resetFilters: () => {
            // Cancel a pending search debounce before it can restore the cleared term.
            actions.setSearchTerm('')
            actions.setDebouncedSearchTerm('')
        },
        moveSearchResult: ({ direction, focus }) => {
            const results = values.searchResults
            if (results.length === 0) {
                return
            }
            const currentIndex = results.findIndex((node) => node.id === values.selectedSearchResult?.id)
            const offset = direction === 'next' ? 1 : -1
            const nextIndex = (currentIndex + offset + results.length) % results.length
            const nodeId = results[nextIndex].id
            if (focus) {
                actions.focusSearchResult(nodeId, direction)
            } else {
                actions.selectSearchResult(nodeId)
            }
        },
        focusSearchResult: ({ nodeId, trigger }) => {
            const resultPosition = values.searchResults.findIndex((node) => node.id === nodeId)
            if (resultPosition !== -1) {
                posthog.capture('models lineage search result focused', {
                    result_count: values.searchResults.length,
                    result_position: resultPosition + 1,
                    search_mode: values.parsedSearchTerm.mode,
                    trigger,
                })
            }
        },
    })),
    selectors({
        parsedSearchTerm: [(s) => [s.searchTerm], (searchTerm: string) => parseLineageSearch(searchTerm)],
        parsedSearch: [(s) => [s.debouncedSearchTerm], (searchTerm: string) => parseLineageSearch(searchTerm)],

        lineageSearchAnchor: [
            (s) => [s.nodes, s.parsedSearchTerm],
            (nodes: DataModelingNode[], parsedSearchTerm: ParsedLineageSearch): DataModelingNode | null =>
                parsedSearchTerm.mode === 'search' ? null : (matchNodesByName(nodes, parsedSearchTerm.term)[0] ?? null),
        ],

        // Both the result list and the graph need the lineage cone. Walking it once here keeps the
        // adjacency maps and the BFS from being built twice for every settled selector search.
        orderedLineageNodes: [
            (s) => [s.nodes, s.edges, s.parsedSearch],
            (
                nodes: DataModelingNode[],
                edges: DataModelingEdge[],
                parsedSearch: ParsedLineageSearch
            ): DataModelingNode[] | null => orderedNodesForLineageSearch(nodes, edges, parsedSearch),
        ],

        // Plain name matching is cheap, so keep its results in step with typing. Lineage selectors
        // wait for the debounce because they prune and lay out the graph again.
        searchResults: [
            (s) => [
                s.nodes,
                s.typeFilter,
                s.parsedSearchTerm,
                s.searchTerm,
                s.debouncedSearchTerm,
                s.orderedLineageNodes,
                s.visibleNodes,
            ],
            (
                nodes: DataModelingNode[],
                typeFilter: DataModelingNodeType[],
                parsedSearchTerm: ParsedLineageSearch,
                searchTerm: string,
                debouncedSearchTerm: string,
                orderedLineageNodes: DataModelingNode[] | null,
                visibleNodes: DataModelingNode[]
            ): DataModelingNode[] => {
                if (parsedSearchTerm.mode === 'search') {
                    const searchableNodes =
                        typeFilter.length === LINEAGE_FILTER_TYPES.length
                            ? nodes
                            : nodes.filter((node) => typeFilter.includes(node.type))
                    return matchNodesByName(searchableNodes, parsedSearchTerm.term)
                }
                if (searchTerm !== debouncedSearchTerm) {
                    return []
                }
                const visibleNodeIds = new Set(visibleNodes.map((node) => node.id))
                return (orderedLineageNodes ?? []).filter((node) => visibleNodeIds.has(node.id))
            },
        ],

        showSearchResults: [
            (s) => [s.parsedSearchTerm, s.searchTerm, s.debouncedSearchTerm, s.nodesLoading, s.edgesLoading],
            (
                parsedSearchTerm: ParsedLineageSearch,
                searchTerm: string,
                debouncedSearchTerm: string,
                nodesLoading: boolean,
                edgesLoading: boolean
            ): boolean => {
                if (parsedSearchTerm.term.length === 0 || nodesLoading) {
                    return false
                }
                // Nodes and edges load in parallel. Only the lineage selectors walk edges, so a
                // plain name search can list results while the edge pages are still arriving. A
                // selector that ran now would report an empty cone as a real answer.
                return parsedSearchTerm.mode === 'search' || (searchTerm === debouncedSearchTerm && !edgesLoading)
            },
        ],

        selectedSearchResult: [
            (s) => [s.searchResults, s.selectedSearchResultId],
            (searchResults: DataModelingNode[], selectedSearchResultId: string | null): DataModelingNode | null =>
                searchResults.find((node) => node.id === selectedSearchResultId) ?? searchResults[0] ?? null,
        ],

        // Read by a live region that stays mounted, so a screen reader announces the first search
        // too. A region inserted with its text already set is not announced.
        searchResultAnnouncement: [
            (s) => [s.showSearchResults, s.searchResults, s.selectedSearchResult],
            (
                showSearchResults: boolean,
                searchResults: DataModelingNode[],
                selectedSearchResult: DataModelingNode | null
            ): string => {
                if (!showSearchResults) {
                    return ''
                }
                if (!selectedSearchResult) {
                    return 'No matching models'
                }
                const position = searchResults.findIndex((node) => node.id === selectedSearchResult.id) + 1
                return `${selectedSearchResult.name}, result ${position} of ${searchResults.length}`
            },
        ],

        highlightedNodeIds: [
            (s) => [s.searchResults, s.parsedSearchTerm],
            (searchResults: DataModelingNode[], parsedSearchTerm: ParsedLineageSearch): Set<string> =>
                parsedSearchTerm.mode === 'search' ? new Set(searchResults.map((node) => node.id)) : new Set(),
        ],

        visibleNodes: [
            (s) => [s.nodes, s.orderedLineageNodes, s.typeFilter],
            (
                nodes: DataModelingNode[],
                orderedLineageNodes: DataModelingNode[] | null,
                typeFilter: DataModelingNodeType[]
            ): DataModelingNode[] => {
                let kept = nodes

                if (orderedLineageNodes) {
                    const reached = new Set(orderedLineageNodes.map((node) => node.id))
                    kept = kept.filter((node) => reached.has(node.id))
                }

                if (typeFilter.length !== LINEAGE_FILTER_TYPES.length) {
                    kept = kept.filter((node) => typeFilter.includes(node.type))
                }

                return kept
            },
        ],

        focusNodeIds: [
            (s) => [s.parsedSearch, s.visibleNodes],
            (parsedSearch: ParsedLineageSearch, visibleNodes: DataModelingNode[]): Set<string> | null => {
                if (parsedSearch.mode === 'search') {
                    return parsedSearch.term ? null : new Set()
                }
                return new Set(visibleNodes.map((node) => node.id))
            },
        ],

        visibleEdges: [
            (s) => [s.edges, s.visibleNodes],
            (edges: DataModelingEdge[], visibleNodes: DataModelingNode[]): DataModelingEdge[] =>
                edgesWithinNodes(edges, new Set(visibleNodes.map((node) => node.id))),
        ],

        isFiltered: [
            (s) => [s.nodes, s.visibleNodes],
            (nodes: DataModelingNode[], visibleNodes: DataModelingNode[]): boolean =>
                visibleNodes.length !== nodes.length,
        ],
    }),
])
