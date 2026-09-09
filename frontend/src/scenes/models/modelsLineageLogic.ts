import { MakeLogicType, actions, connect, kea, path, reducers, selectors } from 'kea'

import { DataModelingEdge, DataModelingNode, DataModelingNodeType } from '~/types'

import { lineageDataLogic } from 'products/data_modeling/frontend/lineage/lineageDataLogic'
import {
    ParsedLineageSearch,
    edgesWithinNodes,
    matchNodesByName,
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
    typeFilter: DataModelingNodeType[]
    legendCollapsed: boolean
    parsedSearch: ParsedLineageSearch
    highlightedNodeIds: Set<string>
    visibleNodes: DataModelingNode[]
    visibleEdges: DataModelingEdge[]
    isFiltered: boolean
}

export interface modelsLineageLogicActions {
    setSearchTerm: (searchTerm: string) => { searchTerm: string }
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
    selectors({
        parsedSearch: [(s) => [s.searchTerm], (searchTerm: string) => parseLineageSearch(searchTerm)],

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
