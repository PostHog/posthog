import { parseSelectAst } from 'lib/monaco/hogqlParser'

import { DataTableNode, DataVisualizationNode, HogQLQuery, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { getTileRecord, getTileString, type AccountViewTileConfig } from './accountViewTileConfig'

// pinned: saved tile queries reference this placeholder name.
export const ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME = 'account_external_id'
export const ACCOUNT_SQL_QUERY_PLACEHOLDER = `{${ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME}}`

type ASTNode = Awaited<ReturnType<typeof parseSelectAst>>

function isAccountSqlQueryFilter(expression: ASTNode | null, aliases: Set<string>): boolean {
    if (expression?.node === 'And') {
        return expression.exprs.some((item: ASTNode) => isAccountSqlQueryFilter(item, aliases))
    }
    if (expression?.node === 'Or') {
        return (
            expression.exprs.length > 0 &&
            expression.exprs.every((item: ASTNode) => isAccountSqlQueryFilter(item, aliases))
        )
    }
    if (expression?.node === 'CompareOperation' && expression.op === '==') {
        return [
            [expression.left, expression.right],
            [expression.right, expression.left],
        ].some(
            ([field, placeholder]) =>
                field.node === 'Field' &&
                !aliases.has(field.chain.join('.')) &&
                placeholder.node === 'Placeholder' &&
                placeholder.expr?.node === 'Field' &&
                placeholder.expr.chain.length === 1 &&
                placeholder.expr.chain[0] === ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME
        )
    }
    return false
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
    if (node.node === 'SelectQuery') {
        if (!node.select_from || !isAccountSqlQueryFilter(node.where, aliases)) {
            return false
        }
    }
    return Object.values(value).every((child) => isAccountSqlQueryAstScoped(child, aliases))
}

export function getAccountSqlQuery(config: AccountViewTileConfig | undefined): string {
    return getTileString(config, 'query')
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

export function getAccountSqlQueryConfigError(config: AccountViewTileConfig): string | undefined {
    const query = getAccountSqlQuery(config)
    if (!query.trim()) {
        return 'Enter a SQL query'
    }
    return query.includes(ACCOUNT_SQL_QUERY_PLACEHOLDER)
        ? undefined
        : `Filter the query by ${ACCOUNT_SQL_QUERY_PLACEHOLDER}`
}

export async function createAccountSqlQueryNode(query: string, externalId: string): Promise<DataTableNode | null> {
    if (!query.trim() || !externalId.trim()) {
        return null
    }
    try {
        const ast = await parseSelectAst(query)
        const aliases = new Set<string>()
        collectAccountSqlQueryAliases(ast, aliases)
        if (!['SelectQuery', 'SelectSetQuery'].includes(ast.node) || !isAccountSqlQueryAstScoped(ast, aliases)) {
            return null
        }
    } catch {
        return null
    }
    return {
        kind: NodeKind.DataTableNode,
        source: {
            kind: NodeKind.HogQLQuery,
            query,
            values: { [ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME]: externalId },
            tags: CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS,
        },
        showTimings: false,
        showOpenEditorButton: false,
        embedded: true,
    }
}
