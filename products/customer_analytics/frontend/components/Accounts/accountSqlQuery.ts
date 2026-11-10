import { DataTableNode, NodeKind } from '~/queries/schema/schema-general'

import { CUSTOMER_ANALYTICS_DEFAULT_QUERY_TAGS } from '../../constants'
import { getTileString, type AccountViewTileConfig } from './accountViewTileConfig'

// pinned: saved tile queries reference this name, and the backend validator requires it.
export const ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME = 'account_external_id'
export const ACCOUNT_SQL_QUERY_PLACEHOLDER = `{${ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME}}`

export function getAccountSqlQuery(config: AccountViewTileConfig | undefined): string {
    return getTileString(config, 'query')
}

export function isAccountSqlQueryScoped(query: string): boolean {
    return query.includes(ACCOUNT_SQL_QUERY_PLACEHOLDER)
}

export function getAccountSqlQueryConfigError(config: AccountViewTileConfig): string | undefined {
    const query = getAccountSqlQuery(config)
    if (!query.trim()) {
        return 'Enter a SQL query'
    }
    return isAccountSqlQueryScoped(query) ? undefined : `Filter the query by ${ACCOUNT_SQL_QUERY_PLACEHOLDER}`
}

export function createAccountSqlQueryNode(query: string, externalId: string): DataTableNode | null {
    if (!query.trim() || !isAccountSqlQueryScoped(query) || !externalId.trim()) {
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
    }
}
