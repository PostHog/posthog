import { MakeLogicType, actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { DataModelingEdge, DataModelingNode, DataModelingNodeType } from '~/types'

import { NodeTypeEnumApi } from '../generated/api.schemas'
import { lineageDataLogic } from './lineageDataLogic'
import {
    ParsedLineageSearch,
    edgesWithinNodes,
    matchNodesByName,
    nodeIdsForLineageSearch,
    parseLineageSearch,
} from './lineageSearch'

export const LINEAGE_FILTER_TYPES: DataModelingNodeType[] = Object.values(NodeTypeEnumApi)

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
    focusNodeIds: Set<string>
    visibleNodes: DataModelingNode[]
    visibleEdges: DataModelingEdge[]
    isFiltered: boolean
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
    listeners(({ actions }) => ({
        // Every keystroke would otherwise prune the graph and start a fresh ELK layout.
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            await breakpoint(250)
            actions.setDebouncedSearchTerm(searchTerm)
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
                return new Set(matchNodesByName(nodes, parsedSearch.term).map((node) => node.id))
            },
        ],

        // The viewport flies here. A plain term matches by substring, so on a big DAG it hits many
        // scattered nodes, and fitting all of them zooms back out to the unreadable overview. Fly to
        // the single closest match instead, because the rest keep their ring and show in the minimap.
        // Match within the visible nodes, since the canvas only lays out those: a closest name that
        // the type filter hides would leave the graph nothing to fit and the viewport would not move.
        // Lineage selectors have already pruned the graph, so there we fit the whole surviving cone.
        focusNodeIds: [
            (s) => [s.parsedSearch, s.visibleNodes],
            (parsedSearch: ParsedLineageSearch, visibleNodes: DataModelingNode[]): Set<string> => {
                if (parsedSearch.mode === 'search') {
                    const best = matchNodesByName(visibleNodes, parsedSearch.term)[0]
                    return best ? new Set([best.id]) : new Set()
                }
                return new Set(visibleNodes.map((node) => node.id))
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
    }),
])
