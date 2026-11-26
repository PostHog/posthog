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

function isAccountSqlJoinFilter(
    expression: ASTNode | null,
    previousAliases: Set<string>,
    sourceAlias: string,
    aliases: Set<string>
): boolean {
    if (expression?.node === 'And') {
        return expression.exprs.some((item: ASTNode) =>
            isAccountSqlJoinFilter(item, previousAliases, sourceAlias, aliases)
        )
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
            previousAliases.has(left.chain[0]) &&
            right.chain[0] === sourceAlias
    )
}

function isAccountSqlJoinScoped(node: ASTNode, aliases: Set<string>): boolean {
    const sourceAliases = new Set<string>()
    let scoped = false
    for (let source = node.select_from; source; source = source.next_join) {
        if (!source.alias || sourceAliases.has(source.alias) || aliases.has(source.alias)) {
            return false
        }
        if (
            sourceAliases.size > 0 &&
            (!['JOIN', 'INNER', 'INNER JOIN'].includes(source.join_type) ||
                source.constraint?.constraint_type !== 'ON' ||
                !isAccountSqlJoinFilter(source.constraint.expr, sourceAliases, source.alias, aliases))
        ) {
            return false
        }
        const allowedFields = getAccountSqlQueryAllowedFields(source)
        const filtered = isAccountSqlQueryFilter(node.where, aliases, allowedFields, source.alias)
        if (allowedFields && !filtered) {
            return false
        }
        scoped ||= filtered || ['SelectQuery', 'SelectSetQuery'].includes(source.table?.node)
        sourceAliases.add(source.alias)
    }
    return scoped
}

function collectAccountSqlQueryAliases(value: unknown, aliases: Set<string>): void {
    if (!value || typeof value !== 'object') {
        return
    }
    const node = value as ASTNode
    if (node.node === 'Alias' || node.node === 'CTE') {
        aliases.add(node.node === 'Alias' ? node.alias : node.name)
    }
    Object.values(value).forEach((child) => collectAccountSqlQueryAliases(child, aliases))
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
    if (
        node.node === 'JoinExpr' &&
        (!['Field', 'SelectQuery', 'SelectSetQuery'].includes(node.table?.node) ||
            node.table_args?.length ||
            node.column_aliases?.length)
    ) {
        return false
    }
    if (node.node === 'SelectQuery') {
        const source = node.select_from
        const allowedFields = source ? getAccountSqlQueryAllowedFields(source) : undefined
        const readsValidatedSubquery = ['SelectQuery', 'SelectSetQuery'].includes(source?.table?.node)
        if (
            !source ||
            (source.next_join
                ? !isAccountSqlJoinScoped(node, aliases)
                : !readsValidatedSubquery && !isAccountSqlQueryFilter(node.where, aliases, allowedFields))
        ) {
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
        const aliases = new Set<string>()
        collectAccountSqlQueryAliases(ast, aliases)
        return ['SelectQuery', 'SelectSetQuery'].includes(ast.node) && isAccountSqlQueryAstScoped(ast, aliases)
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
