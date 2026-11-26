import { parseSelectAst } from 'lib/monaco/hogqlParser'

import { DataTableNode, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { getTileRecord, getTileString, type AccountViewTileConfig } from './accountViewTileConfig'

// pinned: saved tile queries reference this placeholder name.
export const ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME = 'account_external_id'
export const ACCOUNT_SQL_QUERY_PLACEHOLDER = `{${ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME}}`

type ASTNode = Awaited<ReturnType<typeof parseSelectAst>>

function isAccountSqlSourceField(field: ASTNode, aliases: Set<string>): boolean {
    return (
        field.node === 'Field' &&
        !field.chain.some((_: string | number, index: number) => aliases.has(field.chain.slice(0, index + 1).join('.')))
    )
}

function isAccountSqlQueryFilter(
    expression: ASTNode | null,
    aliases: Set<string>,
    allowedFields?: (string | number)[][],
    sourceAlias?: string
): boolean {
    if (expression?.node === 'And') {
        return expression.exprs.some((item: ASTNode) =>
            isAccountSqlQueryFilter(item, aliases, allowedFields, sourceAlias)
        )
    }
    if (expression?.node === 'Or') {
        return (
            expression.exprs.length > 0 &&
            expression.exprs.every((item: ASTNode) =>
                isAccountSqlQueryFilter(item, aliases, allowedFields, sourceAlias)
            )
        )
    }
    if (expression?.node === 'CompareOperation' && expression.op === '==') {
        return [
            [expression.left, expression.right],
            [expression.right, expression.left],
        ].some(
            ([field, placeholder]) =>
                isAccountSqlSourceField(field, aliases) &&
                (!sourceAlias || (field.chain.length >= 2 && field.chain[0] === sourceAlias)) &&
                (!allowedFields ||
                    allowedFields.some(
                        (chain) =>
                            chain.length === field.chain.length &&
                            chain.every((part, index) => part === field.chain[index])
                    )) &&
                placeholder.node === 'Placeholder' &&
                placeholder.expr?.node === 'Field' &&
                placeholder.expr.chain.length === 1 &&
                placeholder.expr.chain[0] === ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME
        )
    }
    return false
}

function getAccountSqlQueryAllowedFields(source: ASTNode): (string | number)[][] | undefined {
    return source.table?.node === 'Field' && source.table.chain.join('.') === 'system.accounts'
        ? [
              ['external_id'],
              ['accounts', 'external_id'],
              ['system', 'accounts', 'external_id'],
              ...(source.alias ? [[source.alias, 'external_id']] : []),
          ]
        : undefined
}

function getAccountSqlQuerySources(node: ASTNode): ASTNode[] {
    const sources = []
    for (let source = node.select_from; source; source = source.next_join) {
        sources.push(source)
    }
    return sources
}

function isAccountSqlProjectedField(
    expression: ASTNode,
    node: ASTNode,
    aliases: Set<string>,
    tail: (string | number)[]
): boolean {
    const field = expression.node === 'Alias' ? expression.expr : expression
    if (!isAccountSqlSourceField(field, aliases) || field.chain.includes('*')) {
        return false
    }
    const sources = getAccountSqlQuerySources(node)
    if (field.chain.length === 1) {
        return (
            sources.length > 0 &&
            sources.every((source) => isAccountSqlJoinSource(source, [...field.chain, ...tail], aliases))
        )
    }
    return sources.some((source) => {
        const prefixes = source.alias
            ? [[source.alias]]
            : source.table?.node === 'Field'
              ? [source.table.chain, source.table.chain.slice(-1)]
              : []
        return prefixes.some(
            (prefix: (string | number)[]) =>
                field.chain.length > prefix.length &&
                prefix.every((part, index) => field.chain[index] === part) &&
                isAccountSqlJoinSource(source, [...field.chain.slice(prefix.length), ...tail], aliases)
        )
    })
}

function getAccountSqlUnionQueries(node: ASTNode): ASTNode[] {
    if (node.node === 'SelectQuery') {
        return [node]
    }
    if (
        node.subsequent_select_queries.some(
            (query: ASTNode) => !['UNION ALL', 'UNION DISTINCT'].includes(query.set_operator)
        )
    ) {
        return []
    }
    const queries: ASTNode[] = []
    for (const query of [
        node.initial_select_query,
        ...node.subsequent_select_queries.map((item: ASTNode) => item.select_query),
    ]) {
        const branches = getAccountSqlUnionQueries(query)
        if (!branches.length) {
            return []
        }
        queries.push(...branches)
    }
    return queries
}

function getAccountSqlProjectionName(expression: ASTNode): string | number | undefined {
    if (expression.node === 'Alias') {
        return expression.alias
    }
    return expression.node === 'Field' ? expression.chain.at(-1) : undefined
}

function collectAccountSqlUnionAliases(node: ASTNode, aliases: Set<string>): void {
    while (node.node === 'SelectSetQuery') {
        node = node.initial_select_query
    }
    collectAccountSqlQueryAliases(node.ctes, aliases)
}

function isAccountSqlExpandingProjection(expression: ASTNode): boolean {
    expression = expression.node === 'Alias' ? expression.expr : expression
    return (
        ['ColumnsExpr', 'SpreadExpr'].includes(expression.node) ||
        (expression.node === 'Field' && expression.chain.includes('*')) ||
        (expression.node === 'Call' && expression.name.toLowerCase() === 'untuple')
    )
}

function isAccountSqlJoinProjection(node: ASTNode, column: (string | number)[], aliases: Set<string>): boolean {
    const queries = getAccountSqlUnionQueries(node)
    if (!queries.length || !column.length) {
        return false
    }
    const firstSelect: ASTNode[] = queries[0].select ?? []
    const positions = firstSelect.flatMap((expression, index) =>
        getAccountSqlProjectionName(expression) === column[0] ? [index] : []
    )
    if (positions.length !== 1) {
        return false
    }
    aliases = new Set(aliases)
    collectAccountSqlUnionAliases(node, aliases)
    return queries.every((query) => {
        const projections: ASTNode[] = query.select ?? []
        if (projections.length !== firstSelect.length || projections.some(isAccountSqlExpandingProjection)) {
            return false
        }
        const localAliases = new Set(aliases)
        const projection = projections[positions[0]]
        Object.values(query).forEach((child) => collectAccountSqlQueryAliases(child, localAliases, projection))
        return isAccountSqlProjectedField(projections[positions[0]], query, localAliases, column.slice(1))
    })
}

function isAccountSqlJoinSource(
    source: ASTNode | undefined,
    column: (string | number)[],
    aliases: Set<string>
): boolean {
    if (!source) {
        return false
    }
    if (source.table?.node === 'Field') {
        return isAccountSqlSourceField(source.table, aliases)
    }
    return (
        ['SelectQuery', 'SelectSetQuery'].includes(source.table?.node) &&
        isAccountSqlJoinProjection(source.table, column, aliases)
    )
}

function isAccountSqlJoinFilter(
    expression: ASTNode | null,
    previousSources: Map<string, ASTNode>,
    source: ASTNode,
    aliases: Set<string>
): boolean {
    if (expression?.node === 'And') {
        return expression.exprs.some((item: ASTNode) => isAccountSqlJoinFilter(item, previousSources, source, aliases))
    }
    if (expression?.node !== 'CompareOperation' || expression.op !== '==') {
        return false
    }
    return [
        [expression.left, expression.right],
        [expression.right, expression.left],
    ].some(
        ([left, right]) =>
            isAccountSqlSourceField(left, aliases) &&
            isAccountSqlSourceField(right, aliases) &&
            left.chain.length >= 2 &&
            right.chain.length >= 2 &&
            previousSources.has(left.chain[0]) &&
            right.chain[0] === source.alias &&
            isAccountSqlJoinSource(previousSources.get(left.chain[0]), left.chain.slice(1), aliases) &&
            isAccountSqlJoinSource(source, right.chain.slice(1), aliases)
    )
}

function isAccountSqlJoinConnected(
    source: ASTNode,
    previousSources: Map<string, ASTNode>,
    aliases: Set<string>
): boolean {
    return (
        previousSources.size === 0 ||
        (['JOIN', 'INNER', 'INNER JOIN'].includes(source.join_type) &&
            source.constraint?.constraint_type === 'ON' &&
            isAccountSqlJoinFilter(source.constraint.expr, previousSources, source, aliases))
    )
}

function isAccountSqlJoinScoped(node: ASTNode, aliases: Set<string>): boolean {
    const sources = new Map<string, ASTNode>()
    let scoped = false
    for (let source = node.select_from; source; source = source.next_join) {
        if (!source.alias || sources.has(source.alias) || aliases.has(source.alias)) {
            return false
        }
        if (!isAccountSqlJoinConnected(source, sources, aliases)) {
            return false
        }
        const allowedFields = getAccountSqlQueryAllowedFields(source)
        const filtered = isAccountSqlQueryFilter(node.where, aliases, allowedFields, source.alias)
        if (allowedFields && !filtered) {
            return false
        }
        scoped ||= filtered || ['SelectQuery', 'SelectSetQuery'].includes(source.table?.node)
        sources.set(source.alias, source)
    }
    return scoped
}

function collectAccountSqlQueryAliases(value: unknown, aliases: Set<string>, definingProjection?: ASTNode): void {
    if (!value || typeof value !== 'object') {
        return
    }
    const node = value as ASTNode
    if (node.node === 'SelectQuery' || node.node === 'SelectSetQuery') {
        return
    }
    if ((node.node === 'Alias' && node !== definingProjection) || node.node === 'CTE') {
        aliases.add(node.node === 'Alias' ? node.alias : node.name)
    }
    Object.values(value).forEach((child) => collectAccountSqlQueryAliases(child, aliases, definingProjection))
}

function isAccountSqlQuerySource(node: ASTNode): boolean {
    return (
        ['Field', 'SelectQuery', 'SelectSetQuery'].includes(node.table?.node) &&
        !node.table_args?.length &&
        !node.column_aliases?.length
    )
}

function isAccountSqlSelectScoped(node: ASTNode, aliases: Set<string>): boolean {
    const source = node.select_from
    if (!source) {
        return false
    }
    if (source.next_join) {
        return isAccountSqlJoinScoped(node, aliases)
    }
    return (
        ['SelectQuery', 'SelectSetQuery'].includes(source.table?.node) ||
        isAccountSqlQueryFilter(node.where, aliases, getAccountSqlQueryAllowedFields(source))
    )
}

function isAccountSqlQueryAstScoped(value: unknown, aliases: Set<string>): boolean {
    if (!value || typeof value !== 'object') {
        return true
    }
    const node = value as ASTNode
    if (node.node === 'Placeholder') {
        return (
            node.expr?.node === 'Field' &&
            node.expr.chain.length === 1 &&
            node.expr.chain[0] === ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME
        )
    }
    if (node.node === 'JoinExpr' && !isAccountSqlQuerySource(node)) {
        return false
    }
    if (node.node === 'SelectSetQuery') {
        aliases = new Set(aliases)
        collectAccountSqlUnionAliases(node, aliases)
    }
    if (node.node === 'SelectQuery') {
        aliases = new Set(aliases)
        Object.values(node).forEach((child) => collectAccountSqlQueryAliases(child, aliases))
        if (!isAccountSqlSelectScoped(node, aliases)) {
            return false
        }
    }
    return Object.values(value).every((child) => isAccountSqlQueryAstScoped(child, aliases))
}

export function getAccountSqlQuery(config: AccountViewTileConfig | undefined): string {
    return getTileString(config, 'query')
}

export function getAccountSqlQuerySourceKind(config: AccountViewTileConfig): 'posthog' | 'clickhouse' {
    return config.connectionId ? 'clickhouse' : 'posthog'
}

export function getAccountSqlQueryConnectionError(connectionId: unknown): string | undefined {
    return connectionId === undefined ||
        (typeof connectionId === 'string' &&
            /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(connectionId))
        ? undefined
        : 'This SQL query has an invalid connection. Edit the tile and choose a connection again.'
}

export function getAccountSqlVisualizationConfig(query: DataVisualizationNode): AccountViewTileConfig {
    return {
        display: query.display ?? ChartDisplayType.ActionsTable,
        ...(query.chartSettings ? { chartSettings: query.chartSettings } : {}),
        ...(query.tableSettings ? { tableSettings: query.tableSettings } : {}),
    }
}

export function createAccountSqlVisualizationNode(
    source: HogQLQuery,
    config: AccountViewTileConfig | undefined
): DataVisualizationNode {
    const visualization = getTileRecord(config, 'visualization') ?? {}
    return {
        kind: NodeKind.DataVisualizationNode,
        source,
        display: Object.values(ChartDisplayType).includes(visualization.display as ChartDisplayType)
            ? (visualization.display as ChartDisplayType)
            : ChartDisplayType.ActionsTable,
        ...(getTileRecord(visualization, 'chartSettings')
            ? { chartSettings: visualization.chartSettings as DataVisualizationNode['chartSettings'] }
            : {}),
        ...(getTileRecord(visualization, 'tableSettings')
            ? { tableSettings: visualization.tableSettings as DataVisualizationNode['tableSettings'] }
            : {}),
    }
}

async function isAccountSqlQueryScoped(query: string): Promise<boolean> {
    try {
        const ast = await parseSelectAst(query)
        return ['SelectQuery', 'SelectSetQuery'].includes(ast.node) && isAccountSqlQueryAstScoped(ast, new Set())
    } catch {
        return false
    }
}

export async function getAccountSqlQueryConfigError(config: AccountViewTileConfig): Promise<string | undefined> {
    const connectionError = getAccountSqlQueryConnectionError(config.connectionId)
    if (connectionError) {
        return connectionError
    }
    const query = getAccountSqlQuery(config)
    if (!query.trim()) {
        return 'Enter a SQL query'
    }
    return (await isAccountSqlQueryScoped(query))
        ? undefined
        : `Filter an account ID column by ${ACCOUNT_SQL_QUERY_PLACEHOLDER} in WHERE. Use INNER JOIN with unique table aliases and column equalities to connect other tables.`
}

export async function createAccountSqlQueryNode(
    query: string,
    externalId: string,
    connectionId?: unknown
): Promise<DataTableNode | null> {
    if (!query.trim() || !externalId.trim() || getAccountSqlQueryConnectionError(connectionId)) {
        return null
    }
    if (!(await isAccountSqlQueryScoped(query))) {
        return null
    }
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query,
            ...(typeof connectionId === 'string' ? { connectionId } : {}),
            values: { [ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME]: externalId },
            tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
        },
        showTimings: false,
        showOpenEditorButton: false,
        embedded: true,
    }
}
