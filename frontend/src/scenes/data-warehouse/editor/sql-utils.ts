import type { ASTNode } from '@posthog/hogql-parser'

import { escapePropertyAsHogQLIdentifier } from '~/queries/utils'

import { parseSelect } from './hogqlParserSingleton'

/** Escape a possibly qualified (dot-separated) name, escaping each segment individually. */
const escapeQualifiedIdentifier = (name: string): string => {
    return name.split('.').map(escapePropertyAsHogQLIdentifier).join('.')
}

export const normalizeIdentifier = (identifier: string): string => {
    return identifier.replace(/[`"']/g, '').toLowerCase()
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

/** Extract the field name string from a select column AST node, or null for non-Field expressions. */
const fieldChainToString = (node: ASTNode): string | null => {
    if (node.node === 'Field') {
        return (node.chain as string[]).join('.')
    }
    return null
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

/** Extract the LIMIT/OFFSET clause string from an AST, or null if absent. */
const extractLimitOffsetFromAST = (ast: ASTNode): string | null => {
    const parts: string[] = []
    if (ast.limit != null && ast.limit.node === 'Constant' && ast.limit.value != null) {
        parts.push(`LIMIT ${ast.limit.value}`)
    }
    if (ast.offset != null && ast.offset.node === 'Constant' && ast.offset.value != null) {
        parts.push(`OFFSET ${ast.offset.value}`)
    }
    return parts.length > 0 ? parts.join(' ') : null
}

export const buildQueryForColumnClick = async (
    currentQuery: string | null,
    tableName: string,
    columnName: string
): Promise<string> => {
    const ast = currentQuery ? await tryParseSelect(currentQuery) : null
    const limitOffsetClause = ast ? extractLimitOffsetFromAST(ast) : null
    const baseQuery = `SELECT ${escapeQualifiedIdentifier(columnName)} FROM ${escapeQualifiedIdentifier(tableName)} ${limitOffsetClause ?? 'LIMIT 100'}`

    if (!ast || !currentQuery) {
        return baseQuery
    }

    const tables = collectTablesFromJoinExpr(ast.select_from)
    if (tables.length === 0) {
        return baseQuery
    }

    const selectedTable = tables[0]
    if (normalizeIdentifier(selectedTable) !== normalizeIdentifier(tableName)) {
        return baseQuery
    }

    const selectNodes: ASTNode[] = ast.select ?? []
    const fieldNames = selectNodes.map(fieldChainToString)
    const hasNonFieldExpressions = fieldNames.some((name) => name === null)

    // If the query contains non-Field expressions (e.g. COUNT(*), SUM(x)),
    // we can't safely rewrite the SELECT list — fall back to a simple query.
    if (hasNonFieldExpressions) {
        return baseQuery
    }

    let columns = fieldNames as string[]
    const normalizedColumnName = normalizeIdentifier(columnName)
    const isStarOnly = columns.length === 1 && columns[0] === '*'

    if (isStarOnly) {
        columns = []
    } else {
        columns = columns.filter((column) => column !== '*')
    }

    const existingIndex = columns.findIndex((column) => normalizeIdentifier(column) === normalizedColumnName)

    if (existingIndex >= 0) {
        columns.splice(existingIndex, 1)
    } else {
        columns.push(columnName)
    }

    if (columns.length === 0) {
        columns = ['*']
    }

    return `SELECT ${columns.map((column) => (column === '*' ? column : escapeQualifiedIdentifier(column))).join(', ')} FROM ${escapeQualifiedIdentifier(tableName)} ${limitOffsetClause ?? 'LIMIT 100'}`
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
