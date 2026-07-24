import type { ASTNode } from '@posthog/hogql-parser'

import { parseSelect } from './hogqlParserSingleton'

export const normalizeIdentifier = (identifier: string): string => {
    return identifier.replace(/[`"']/g, '').toLowerCase()
}

export const queryUsesFiltersPlaceholder = (query: string | null): boolean => {
    if (!query) {
        return false
    }

    let i = 0
    while (i < query.length) {
        const ch = query[i]

        if (ch === "'" || ch === '"' || ch === '`') {
            const quote = ch
            i++
            while (i < query.length) {
                if (query[i] === '\\') {
                    i += 2
                    continue
                }
                if (query[i] === quote && query[i + 1] === quote) {
                    i += 2
                    continue
                }
                if (query[i] === quote) {
                    i++
                    break
                }
                i++
            }
            continue
        }

        if (ch === '-' && query[i + 1] === '-') {
            i += 2
            while (i < query.length && query[i] !== '\n') {
                i++
            }
            continue
        }

        if (ch === '/' && query[i + 1] === '*') {
            i += 2
            while (i < query.length) {
                if (query[i] === '*' && query[i + 1] === '/') {
                    i += 2
                    break
                }
                i++
            }
            continue
        }

        if (query.startsWith('{filters}', i) || query.startsWith('{filters.', i)) {
            return true
        }

        i++
    }

    return false
}

/** Try to parse a SELECT query, returning the AST node or null on failure. */
const tryParseSelect = async (query: string): Promise<ASTNode | null> => {
    try {
        const result = JSON.parse(await parseSelect(query))
        if (result.error || result.node !== 'SelectQuery') {
            return null
        }
        return result as ASTNode
    } catch {
        return null
    }
}

/** Collect all table names from a JoinExpr chain. */
const collectTablesFromJoinExpr = (joinExpr: ASTNode | null): string[] => {
    const tables: string[] = []
    let current = joinExpr
    while (current) {
        if (current.table?.node === 'Field') {
            tables.push((current.table.chain as string[]).join('.'))
        }
        current = current.next_join ?? null
    }
    return tables
}

export const parseQueryTablesAndColumns = async (
    queryInput: string | null
): Promise<Record<string, Record<string, boolean>>> => {
    if (!queryInput) {
        return {}
    }

    const ast = await tryParseSelect(queryInput)
    if (!ast) {
        return {}
    }

    const selectedTables = collectTablesFromJoinExpr(ast.select_from)
    if (selectedTables.length === 0) {
        return {}
    }

    const selectedColumnsByTable: Record<string, Record<string, boolean>> = {}
    const selectNodes: ASTNode[] = ast.select ?? []

    for (const node of selectNodes) {
        // Handle SELECT *
        if (node.node === 'Field' && node.chain.length === 1 && node.chain[0] === '*') {
            for (const table of selectedTables) {
                selectedColumnsByTable[table] = {
                    '*': true,
                    ...selectedColumnsByTable[table],
                }
            }
            continue
        }

        if (node.node === 'Field') {
            const chain = node.chain as string[]

            // table.column form
            if (chain.length >= 2) {
                const tablePrefix = chain.slice(0, -1).join('.')
                const col = chain[chain.length - 1]
                const tableKey = selectedTables.find(
                    (table) => normalizeIdentifier(table) === normalizeIdentifier(tablePrefix)
                )
                if (tableKey) {
                    selectedColumnsByTable[tableKey] = {
                        [col]: true,
                        ...selectedColumnsByTable[tableKey],
                    }
                    continue
                }
            }

            // Bare column — assign to first table
            const fallbackTable = selectedTables[0]
            selectedColumnsByTable[fallbackTable] = {
                [chain.join('.')]: true,
                ...selectedColumnsByTable[fallbackTable],
            }
        }
    }

    return selectedColumnsByTable
}
