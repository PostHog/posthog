import { actions, connect, kea, listeners, path, reducers, selectors } from 'kea'

import { DataModelingNode } from '~/types'

import type { dataModelingNodesLogicType } from './dataModelingNodesLogicType'
import { dataModelingEditorLogic } from './modeling/dataModelingEditorLogic'

export const PAGE_SIZE = 10

export type SearchMode = 'search' | 'upstream' | 'downstream' | 'all'

export interface ParsedSearch {
    mode: SearchMode
    baseName: string
}

/** Parse search term for +name (upstream), name+ (downstream), or +name+ (both) syntax */
export function parseSearchTerm(searchTerm: string): ParsedSearch {
    const trimmed = searchTerm.trim()
    if (trimmed.startsWith('+') && trimmed.endsWith('+') && trimmed.length > 2) {
        return { mode: 'all', baseName: trimmed.slice(1, -1) }
    }
    if (trimmed.startsWith('+') && trimmed.length > 1) {
        return { mode: 'upstream', baseName: trimmed.slice(1) }
    }
    if (trimmed.endsWith('+') && trimmed.length > 1) {
        return { mode: 'downstream', baseName: trimmed.slice(0, -1) }
    }
    return { mode: 'search', baseName: trimmed }
}

export const dataModelingNodesLogic = kea<dataModelingNodesLogicType>([
    path(['scenes', 'data-warehouse', 'scene', 'dataModelingNodesLogic']),
    connect(() => ({
        values: [dataModelingEditorLogic, ['dataModelingNodes as nodes', 'dataModelingNodesLoading as nodesLoading']],
    })),
    actions({
        setSearchTerm: (searchTerm: string) => ({ searchTerm }),
        setDebouncedSearchTerm: (debouncedSearchTerm: string) => ({ debouncedSearchTerm }),
        setCurrentPage: (page: number) => ({ page }),
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
        parsedSearch: [
            (s) => [s.debouncedSearchTerm],
            (debouncedSearchTerm: string): ParsedSearch => parseSearchTerm(debouncedSearchTerm),
        ],
        filteredNodes: [
            (s) => [s.nodes, s.searchTerm],
            (nodes: DataModelingNode[], searchTerm: string): DataModelingNode[] => {
                if (!searchTerm) {
                    return nodes
                }
                const { baseName } = parseSearchTerm(searchTerm)
                return nodes.filter((n) => n.name.toLowerCase().includes(baseName.toLowerCase()))
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
])
