import type { TreeDataItem } from 'lib/lemon-ui/LemonTree/LemonTree'

export const MATERIALIZATION_STATUS_FILTER_OPTIONS = ['Failed', 'Running', 'Completed'] as const
export type MaterializationStatusFilter = (typeof MATERIALIZATION_STATUS_FILTER_OPTIONS)[number]

export interface ParsedDatabaseSearch {
    searchText: string
    materializationStatusFilters: MaterializationStatusFilter[]
}

const MATERIALIZATION_STATUS_BY_TOKEN = new Map(
    MATERIALIZATION_STATUS_FILTER_OPTIONS.map((status) => [status.toLowerCase(), status])
)
const MATERIALIZATION_STATUS_TOKEN_PATTERN = /^status:(failed|running|completed)$/i

export function parseDatabaseSearch(searchTerm: string): ParsedDatabaseSearch {
    const materializationStatusFilters: MaterializationStatusFilter[] = []
    const searchTokens: string[] = []

    for (const token of searchTerm.trim().split(/\s+/).filter(Boolean)) {
        const statusToken = token.match(MATERIALIZATION_STATUS_TOKEN_PATTERN)?.[1].toLowerCase()
        const status = statusToken ? MATERIALIZATION_STATUS_BY_TOKEN.get(statusToken) : undefined

        if (status) {
            if (!materializationStatusFilters.includes(status)) {
                materializationStatusFilters.push(status)
            }
        } else {
            searchTokens.push(token)
        }
    }

    return {
        searchText: searchTokens.join(' '),
        materializationStatusFilters,
    }
}

function buildDatabaseSearch(searchText: string, statuses: MaterializationStatusFilter[]): string {
    return [searchText, ...statuses.map((status) => `status:${status.toLowerCase()}`)].filter(Boolean).join(' ')
}

export function toggleMaterializationStatusSearchToken(
    searchTerm: string,
    status: MaterializationStatusFilter
): string {
    const { searchText, materializationStatusFilters } = parseDatabaseSearch(searchTerm)
    const statuses = materializationStatusFilters.includes(status)
        ? materializationStatusFilters.filter((value) => value !== status)
        : [...materializationStatusFilters, status]

    return buildDatabaseSearch(searchText, statuses)
}

export function clearMaterializationStatusSearchTokens(searchTerm: string): string {
    return parseDatabaseSearch(searchTerm).searchText
}

export function matchesMaterializationStatus(
    view: { is_materialized?: boolean; status?: string | null },
    statuses: MaterializationStatusFilter[]
): boolean {
    return statuses.length === 0 || Boolean(view.is_materialized && statuses.some((status) => view.status === status))
}

export function filterMaterializedViewsByStatus(
    items: TreeDataItem[],
    statuses: MaterializationStatusFilter[]
): TreeDataItem[] {
    if (statuses.length === 0) {
        return items
    }

    return items.flatMap((item) => {
        if (item.record?.type === 'view') {
            return item.record.view && matchesMaterializationStatus(item.record.view, statuses) ? [item] : []
        }

        if (item.type === 'loading-indicator') {
            return [item]
        }

        if (item.record?.type === 'views' || item.record?.folderType === 'view-folder') {
            const children = filterMaterializedViewsByStatus(item.children ?? [], statuses)
            return children.length ? [{ ...item, children }] : []
        }

        return []
    })
}
