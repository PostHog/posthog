import { LemonBanner } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'

import { ACCOUNT_SQL_QUERY_PLACEHOLDER, createAccountSqlQueryNode, getAccountSqlQuery } from './accountSqlQuery'
import type { AccountViewTileConfig } from './accountViewTileConfig'

interface AccountSqlQueryTileProps {
    externalId: string
    instanceId?: string
    initialConfig?: AccountViewTileConfig
}

export function AccountSqlQueryTile({ externalId, instanceId, initialConfig }: AccountSqlQueryTileProps): JSX.Element {
    const query = getAccountSqlQuery(initialConfig)
    if (!query.trim()) {
        return (
            <p className="m-0 pb-2 text-sm text-secondary">
                Edit this tile to add a SQL query. Use {ACCOUNT_SQL_QUERY_PLACEHOLDER} to filter results to this
                account.
            </p>
        )
    }
    const node = createAccountSqlQueryNode(query, externalId)
    if (!node) {
        return (
            <LemonBanner type="warning" className="mb-2">
                {externalId.trim()
                    ? `Edit this tile and filter the query by ${ACCOUNT_SQL_QUERY_PLACEHOLDER} to show results for this account.`
                    : "This account isn't linked to analytics data yet, so the query can't be filtered to it."}
            </LemonBanner>
        )
    }
    return (
        <Query
            query={node}
            context={{
                insightProps: { dashboardItemId: `new-account-sql-query-${instanceId ?? 'tile'}-${externalId}` },
            }}
            readOnly
            embedded
        />
    )
}
