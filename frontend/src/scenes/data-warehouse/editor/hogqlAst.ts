import type { ASTNode } from '@posthog/hogql-parser'

// Walks over an already-parsed HogQL AST. Kept free of any parsing so the same code can run in
// the parser worker and in the main-thread fallback — the worker returns these small results
// instead of the AST itself, which runs to megabytes on a long query.

export interface AstRange {
    /** 0-based character offset within the parsed query text */
    start: number
    end: number
}

/**
 * Collect all SelectQuery/SelectSetQuery nodes whose position range contains the target offset.
 */
function collectSelectNodesAtOffset(node: unknown, targetOffset: number, results: ASTNode[]): void {
    if (node === null || node === undefined || typeof node !== 'object') {
        return
    }

    if (Array.isArray(node)) {
        for (const item of node) {
            collectSelectNodesAtOffset(item, targetOffset, results)
        }
        return
    }

    const astNode = node as ASTNode
    if (
        (astNode.node === 'SelectQuery' || astNode.node === 'SelectSetQuery') &&
        astNode.start?.offset != null &&
        astNode.end?.offset != null &&
        targetOffset >= astNode.start.offset &&
        targetOffset <= astNode.end.offset
    ) {
        results.push(astNode)
    }

    // Recurse into all object values
    for (const value of Object.values(astNode)) {
        if (typeof value === 'object' && value !== null) {
            collectSelectNodesAtOffset(value, targetOffset, results)
        }
    }
}

/**
 * Range of the innermost SELECT subquery containing the offset, or null when the offset is only
 * inside the outermost SELECT (no nesting).
 */
export function innermostSelectRangeFromAst(ast: ASTNode, localOffset: number): AstRange | null {
    if (ast.error || (ast.node !== 'SelectQuery' && ast.node !== 'SelectSetQuery')) {
        return null
    }

    const results: ASTNode[] = []
    collectSelectNodesAtOffset(ast, localOffset, results)

    // Need at least 2 matches (outer + inner) to have a subquery
    if (results.length < 2) {
        return null
    }

    // Pick the node with the smallest span. JSON key iteration order is not guaranteed
    // to produce children after siblings, so depth-by-order is unreliable — but for any
    // nested pair of SELECTs containing the cursor, the inner one always has a smaller
    // range than any ancestor.
    const innermost = results.reduce((smallest, candidate) => {
        const smallestSpan = smallest.end.offset - smallest.start.offset
        const candidateSpan = candidate.end.offset - candidate.start.offset
        return candidateSpan < smallestSpan ? candidate : smallest
    })

    return { start: innermost.start.offset, end: innermost.end.offset }
}

export const normalizeIdentifier = (identifier: string): string => {
    return identifier.replace(/[`"']/g, '').toLowerCase()
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

/** Which columns of which selected tables the query's SELECT list references. */
export function tablesAndColumnsFromAst(ast: ASTNode): Record<string, Record<string, boolean>> {
    if (ast.error || ast.node !== 'SelectQuery') {
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
