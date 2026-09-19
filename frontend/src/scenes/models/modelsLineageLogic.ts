import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import { DataModelingEdge, DataModelingNode, DataModelingNodeType } from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import {
    ParsedLineageSearch,
    edgesWithinNodes,
    matchNodes,
    nodeIdsForLineageSearch,
    parseLineageSearch,
} from 'products/data_modeling/frontend/lineage/lineageSearch'

export const LINEAGE_FILTER_TYPES: DataModelingNodeType[] = ['table', 'view', 'matview', 'endpoint']

export interface modelsLineageLogicValues {
    nodes: DataModelingNode[] // lineageDataLogic
    nodesLoading: boolean // lineageDataLogic
    edges: DataModelingEdge[] // lineageDataLogic
    edgesLoading: boolean // lineageDataLogic
    searchTerm: string
    debouncedSearchTerm: string
    typeFilter: DataModelingNodeType[]
    legendCollapsed: boolean
    parsedSearch: ParsedLineageSearch
    highlightedNodeIds: Set<string>
    visibleNodes: DataModelingNode[]
    visibleEdges: DataModelingEdge[]
    isFiltered: boolean
    searchMatchCount: number | null
    hasActiveFilters: boolean
}

export interface modelsLineageLogicActions {
    setSearchTerm: (searchTerm: string) => { searchTerm: string }
    setDebouncedSearchTerm: (searchTerm: string) => { searchTerm: string }
    setTypeFilter: (typeFilter: DataModelingNodeType[]) => { typeFilter: DataModelingNodeType[] }
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
    }),
    listeners(({ actions, values }) => ({
        // Every keystroke would otherwise prune the graph and start a fresh ELK layout.
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            await breakpoint(250)
            actions.setDebouncedSearchTerm(searchTerm)

            // Let typing settle further, so one search reports once rather than once per pause.
            await breakpoint(750)
            const term = searchTerm.trim()
            if (!term) {
                return
            }
            posthog.capture('lineage searched', {
                // Model names are customer data, so only the shape of the term is reported.
                term_length: term.length,
                mode: values.parsedSearch.mode,
                // A plain term highlights and a `+` selector prunes, but either way this is what
                // came back, which is what tells a failed search from a successful one.
                match_count: values.searchMatchCount ?? values.visibleNodes.length,
                node_count: values.nodes.length,
            })
        },
    })),
    selectors({
        parsedSearch: [(s) => [s.debouncedSearchTerm], (searchTerm: string) => parseLineageSearch(searchTerm)],

        // A plain term highlights matches in place. Only the `+` lineage selectors prune the canvas,
        // so typing a single letter never empties the graph.
        highlightedNodeIds: [
            (s) => [s.nodes, s.parsedSearch],
            (nodes: DataModelingNode[], parsedSearch: ParsedLineageSearch): Set<string> => {
                if (parsedSearch.mode !== 'search') {
                    return new Set()
                }
                return new Set(matchNodes(nodes, parsedSearch.term).map((node) => node.id))
            },
        ],

        visibleNodes: [
            (s) => [s.nodes, s.edges, s.parsedSearch, s.typeFilter],
            (
                nodes: DataModelingNode[],
                edges: DataModelingEdge[],
                parsedSearch: ParsedLineageSearch,
                typeFilter: DataModelingNodeType[]
            ): DataModelingNode[] => {
                let kept = nodes

                const reached = nodeIdsForLineageSearch(nodes, edges, parsedSearch)
                if (reached) {
                    kept = kept.filter((node) => reached.has(node.id))
                }

                if (typeFilter.length !== LINEAGE_FILTER_TYPES.length) {
                    kept = kept.filter((node) => typeFilter.includes(node.type))
                }

                return kept
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

        // Null when no plain term is typed, so the scene can tell "nothing searched yet" from
        // "nothing matched" — the two look identical while a plain term prunes nothing.
        searchMatchCount: [
            (s) => [s.parsedSearch, s.highlightedNodeIds, s.visibleNodes],
            (
                parsedSearch: ParsedLineageSearch,
                highlightedNodeIds: Set<string>,
                visibleNodes: DataModelingNode[]
            ): number | null =>
                parsedSearch.mode === 'search' && parsedSearch.term
                    ? visibleNodes.filter((node) => highlightedNodeIds.has(node.id)).length
                    : null,
        ],

        hasActiveFilters: [
            (s) => [s.isFiltered, s.searchMatchCount],
            (isFiltered: boolean, searchMatchCount: number | null): boolean => isFiltered || searchMatchCount !== null,
        ],
    }),
])
