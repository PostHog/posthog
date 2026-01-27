import { actions, afterMount, kea, listeners, path, reducers, selectors } from 'kea'
import { loaders } from 'kea-loaders'

import api from 'lib/api'

import { DataModelingNode } from '~/types'

import type { dataModelingNodesLogicType } from './dataModelingNodesLogicType'
import { dataModelingEditorLogic } from './modeling/dataModelingEditorLogic'

export const PAGE_SIZE = 10

export const dataModelingNodesLogic = kea<dataModelingNodesLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'dataModelingNodesLogic']),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setDebouncedSearchTerm: (debouncedSearchTerm: string) => ({ debouncedSearchTerm }),
        setCurrentPage: (page: number) => ({ page }),
    }),
    loaders({
        nodes: [
            [] as DataModelingNode[],
            {
                loadNodes: async () => {
                    const response = await api.dataModelingNodes.list()
                    return response.results
                },
            },
        ],
    }),
    reducers({
        searchTerm: [
            '' as string,
            {
                setSearchTerm: (_, { searchTerm }) => searchTerm,
            },
        ],
        debouncedSearchTerm: [
            '' as string,
            {
                setDebouncedSearchTerm: (_, { debouncedSearchTerm }) => debouncedSearchTerm,
            },
        ],
        currentPage: [
            1 as number,
            {
                setCurrentPage: (_, { page }) => page,
                setSearchTerm: () => 1,
            },
        ],
    }),
    selectors({
        filteredNodes: [
            (s) => [s.nodes, s.searchTerm],
            (nodes: DataModelingNode[], searchTerm: string): DataModelingNode[] => {
                if (!searchTerm) {
                    return nodes
                }
                return nodes.filter((n) => n.name.toLowerCase().includes(searchTerm.toLowerCase()))
            },
        ],
        viewNodes: [
            (s) => [s.filteredNodes],
            (nodes: DataModelingNode[]): DataModelingNode[] => {
                return nodes.filter((n) => n.type === 'matview' || n.type === 'view')
            },
        ],
        visibleNodes: [
            (s) => [s.viewNodes, s.currentPage],
            (nodes: DataModelingNode[], currentPage: number): DataModelingNode[] => {
                const startIndex = (currentPage - 1) * PAGE_SIZE
                const endIndex = startIndex + PAGE_SIZE
                return nodes.slice(startIndex, endIndex)
            },
        ],
    }),
    listeners(({ actions }) => ({
        setSearchTerm: async ({ searchTerm }, breakpoint) => {
            if (searchTerm.length > 0) {
                dataModelingEditorLogic.actions.setHighlightedNodeType(null)
            }
            await breakpoint(150)
            actions.setDebouncedSearchTerm(searchTerm)
        },
    })),
    afterMount(({ actions }) => {
        actions.loadNodes()
    }),
])
