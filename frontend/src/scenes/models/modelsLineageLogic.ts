import { MakeLogicType, actions, afterMount, connect, kea, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataModelingEdge, DataModelingNode, DataModelingNodeType } from '~/types'

import {
    ParsedLineageSearch,
    buildAdjacencyMaps,
    edgesWithinNodes,
    matchNodesByName,
    parseLineageSearch,
    traverseLineage,
} from 'products/data_modeling/frontend/lineage/lineageSearch'

import { modelsSceneLogic } from './modelsSceneLogic'

export const LINEAGE_FILTER_TYPES: DataModelingNodeType[] = ['table', 'view', 'matview', 'endpoint']

export interface modelsLineageLogicValues {
    nodes: DataModelingNode[] // modelsSceneLogic
    nodesLoading: boolean // modelsSceneLogic
    searchTerm: string
    typeFilter: DataModelingNodeType[]
    legendCollapsed: boolean
    edges: DataModelingEdge[]
    edgesLoading: boolean
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
    loadEdges: () => any
    loadEdgesFailure: (error: string, errorObject?: any) => { error: string; errorObject?: any }
    loadEdgesSuccess: (edges: DataModelingEdge[], payload?: any) => { edges: DataModelingEdge[]; payload?: any }
}

export type modelsLineageLogicType = MakeLogicType<modelsLineageLogicValues, modelsLineageLogicActions>

export const modelsLineageLogic = kea<modelsLineageLogicType>([
    path(['scenes', 'models', 'modelsLineageLogic']),
    connect(() => ({
        values: [modelsSceneLogic, ['nodes', 'nodesLoading']],
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
    loaders({
        edges: {
            __default: [] as DataModelingEdge[],
            loadEdges: async () => {
                const response = await api.dataModelingEdges.list()
                return response.results
            },
        },
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

                if (parsedSearch.mode !== 'search' && parsedSearch.term) {
                    const anchor = matchNodesByName(nodes, parsedSearch.term)[0]
                    // An unmatched anchor means the term names nothing, so nothing is in the result
                    const reached = anchor
                        ? traverseLineage(anchor.id, buildAdjacencyMaps(edges), parsedSearch.mode)
                        : new Set<string>()
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
    afterMount(({ actions }) => {
        actions.loadEdges()
    }),
])
