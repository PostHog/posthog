import type { ASTNode } from '@posthog/hogql-parser'

export interface SqlTableReference {
    name: string
    start: number
    end: number
}

function referenceInJoin(ast: ASTNode, offset: number, ctes: Set<string>): SqlTableReference | null {
    if (ast.node !== 'JoinExpr' || ast.table?.node !== 'Field') {
        return null
    }
    const field = ast.table
    if (field.start?.offset == null || field.end?.offset == null) {
        return null
    }
    const name = field.chain.join('.')
    return offset >= field.start.offset && offset < field.end.offset && !ctes.has(name)
        ? { name, start: field.start.offset, end: field.end.offset }
        : null
}

function referenceInSelectSet(
    ast: ASTNode,
    offset: number,
    ctes: Set<string>,
    recursiveName?: string
): SqlTableReference | null {
    const initial = tableReferenceFromAst(ast.initial_select_query, offset, ctes)
    if (initial) {
        return initial
    }
    const scope = new Set(ctes)
    for (const cte of ast.initial_select_query?.ctes ?? []) {
        scope.add(cte.name)
    }
    if (recursiveName) {
        scope.add(recursiveName)
    }
    return tableReferenceFromAst(ast.subsequent_select_queries, offset, scope)
}

function referenceInSelect(ast: ASTNode, offset: number, ctes: Set<string>): SqlTableReference | null {
    const scope = new Set(ctes)
    for (const cte of ast.ctes ?? []) {
        const reference =
            cte.recursive && cte.expr?.node === 'SelectSetQuery'
                ? referenceInSelectSet(cte.expr, offset, scope, cte.name)
                : tableReferenceFromAst(cte.expr, offset, scope)
        if (reference) {
            return reference
        }
        scope.add(cte.name)
    }
    const { ctes: _ctes, ...body } = ast
    return referenceInChildren(body, offset, scope)
}

function referenceInChildren(ast: ASTNode, offset: number, ctes: Set<string>): SqlTableReference | null {
    for (const child of Object.values(ast)) {
        const reference = tableReferenceFromAst(child, offset, ctes)
        if (reference) {
            return reference
        }
    }
    return null
}

export function tableReferenceFromAst(
    node: unknown,
    offset: number,
    ctes = new Set<string>()
): SqlTableReference | null {
    if (!node || typeof node !== 'object') {
        return null
    }
    const ast = node as ASTNode
    if (ast.error) {
        return null
    }
    if (ast.node === 'SelectSetQuery') {
        return referenceInSelectSet(ast, offset, ctes)
    }
    if (ast.node === 'SelectQuery') {
        return referenceInSelect(ast, offset, ctes)
    }
    return referenceInJoin(ast, offset, ctes) ?? referenceInChildren(ast, offset, ctes)
}
