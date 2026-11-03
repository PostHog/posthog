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
const MATERIALIZATION_STATUS_TOKENS = MATERIALIZATION_STATUS_FILTER_OPTIONS.map(
    (status) => `status:${status.toLowerCase()}`
)

const tokenizeDatabaseSearch = (searchTerm: string): string[] => searchTerm.trim().split(/\s+/).filter(Boolean)

export function parseDatabaseSearch(searchTerm: string): ParsedDatabaseSearch {
    const materializationStatusFilters: MaterializationStatusFilter[] = []
    const searchTokens: string[] = []

    for (const token of tokenizeDatabaseSearch(searchTerm)) {
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

export function databaseSearchNeedsFieldHydration(searchTerm: string): boolean {
    return tokenizeDatabaseSearch(searchTerm).some(
        (token) => !MATERIALIZATION_STATUS_TOKENS.some((statusToken) => statusToken.startsWith(token.toLowerCase()))
    )
}

function removeMaterializationStatusSearchTokens(searchTerm: string, status?: MaterializationStatusFilter): string {
    const tokenMatches = [...searchTerm.matchAll(/\S+/g)].filter((match) => {
        const parsedStatus = match[0].match(MATERIALIZATION_STATUS_TOKEN_PATTERN)?.[1].toLowerCase()
        return parsedStatus && (!status || parsedStatus === status.toLowerCase())
    })
    let result = searchTerm

    for (const match of tokenMatches.reverse()) {
        let start = match.index
        let end = start + match[0].length

        if (start === 0) {
            while (end < result.length && /\s/.test(result[end])) {
                end++
            }
        } else {
            while (start > 0 && /\s/.test(result[start - 1])) {
                start--
            }
        }

        result = result.slice(0, start) + result.slice(end)
    }

    return result
}

export function toggleMaterializationStatusSearchToken(
    searchTerm: string,
    status: MaterializationStatusFilter
): string {
    const { materializationStatusFilters } = parseDatabaseSearch(searchTerm)
    if (materializationStatusFilters.includes(status)) {
        return removeMaterializationStatusSearchTokens(searchTerm, status)
    }

    const separator = searchTerm && !/\s$/.test(searchTerm) ? ' ' : ''
    return `${searchTerm}${separator}status:${status.toLowerCase()}`
}

export function clearMaterializationStatusSearchTokens(searchTerm: string): string {
    return removeMaterializationStatusSearchTokens(searchTerm)
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
