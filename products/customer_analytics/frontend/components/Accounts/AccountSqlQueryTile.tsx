import { useValues } from 'kea'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'

import { ACCOUNT_SQL_QUERY_PLACEHOLDER, getAccountSqlQuery } from './accountSqlQuery'
import { accountSqlQueryLogic } from './accountSqlQueryLogic'
import type { AccountViewTileConfig } from './accountViewTileConfig'

interface AccountSqlQueryTileProps {
    accountId: string
    externalId: string
    instanceId?: string
    initialConfig?: AccountViewTileConfig
}

export function AccountSqlQueryTile({
    accountId,
    externalId,
    instanceId,
    initialConfig,
}: AccountSqlQueryTileProps): JSX.Element {
    const query = getAccountSqlQuery(initialConfig)
    const { queryNode: node, queryNodeLoading } = useValues(
        accountSqlQueryLogic({ accountId, externalId, instanceId, query })
    )
    if (!query.trim()) {
        return (
            <p className="m-0 pb-2 text-sm text-secondary">
                Edit this tile to add a SQL query. Use {ACCOUNT_SQL_QUERY_PLACEHOLDER} to filter results to this
                account.
            </p>
        )
    }
    if (queryNodeLoading) {
        return <Spinner />
    }
    if (!node) {
        return (
            <LemonBanner type="warning" className="mb-2">
                {externalId.trim()
                    ? `Couldn't validate this query. Edit this tile and add a column = ${ACCOUNT_SQL_QUERY_PLACEHOLDER} filter to every SELECT's WHERE clause.`
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
