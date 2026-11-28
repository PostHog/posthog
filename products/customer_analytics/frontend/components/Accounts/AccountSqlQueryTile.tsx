import './AccountSqlQueryTile.scss'

import clsx from 'clsx'
import { useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { LemonBanner, Spinner } from '@posthog/lemon-ui'

import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import {
    ACCOUNT_SQL_QUERY_PLACEHOLDER,
    createAccountSqlVisualizationNode,
    getAccountSqlQuery,
    getAccountSqlQueryConnectionError,
} from './accountSqlQuery'
import { accountSqlQueryLogic } from './accountSqlQueryLogic'
import type { AccountViewTileConfig } from './accountViewTileConfig'

interface AccountSqlQueryTileProps {
    accountId: string
    externalId: string
    instanceId?: string
    initialConfig?: AccountViewTileConfig
    onVisualizationChange?: (query: DataVisualizationNode) => void
    onLoadingChange?: (loading: boolean) => void
}

export function AccountSqlQueryTile({
    accountId,
    externalId,
    instanceId,
    initialConfig,
    onVisualizationChange,
    onLoadingChange,
}: AccountSqlQueryTileProps): JSX.Element {
    const [resultLoading, setResultLoading] = useState(true)
    const query = getAccountSqlQuery(initialConfig)
    const connectionId = initialConfig?.connectionId
    const connectionError = getAccountSqlQueryConnectionError(connectionId)
    const {
        queryNode: node,
        queryNodeLoading,
        queryKey,
    } = useValues(accountSqlQueryLogic({ accountId, externalId, instanceId, query, connectionId }))
    const visualization = useMemo(
        () =>
            node && node.source.kind === NodeKind.HogQLQuery && (initialConfig?.visualization || onVisualizationChange)
                ? createAccountSqlVisualizationNode(node.source, initialConfig)
                : null,
        [node, initialConfig, onVisualizationChange]
    )
    const isSavedChart =
        !!visualization && visualization.display !== ChartDisplayType.ActionsTable && !onVisualizationChange
    useEffect(() => {
        onLoadingChange?.(queryNodeLoading || (!!node && resultLoading))
    }, [onLoadingChange, queryNodeLoading, node, resultLoading])
    useEffect(() => () => onLoadingChange?.(false), [onLoadingChange])
    if (connectionError) {
        return <LemonBanner type="error">{connectionError}</LemonBanner>
    }
    if (!query.trim()) {
        return (
            <p className="m-0 pb-2 text-sm text-secondary">
                Edit this tile to add a SQL query. Use {ACCOUNT_SQL_QUERY_PLACEHOLDER} to filter results to this
                account.
            </p>
        )
    }
    if (queryNodeLoading) {
        return onLoadingChange ? <></> : <Spinner />
    }
    if (!node) {
        return (
            <LemonBanner type="warning" className="mb-2">
                {externalId.trim()
                    ? `Couldn't validate this query. Edit this tile and check its ${ACCOUNT_SQL_QUERY_PLACEHOLDER} filter and INNER JOIN conditions.`
                    : "This account isn't linked to analytics data yet, so the query can't be filtered to it."}
            </LemonBanner>
        )
    }
    return (
        <div
            className={clsx('AccountSqlQueryTile ph-no-capture', {
                'AccountSqlQueryTile--chart flex h-80 flex-col has-[.DataVisualizationTable]:h-auto': isSavedChart,
                'AccountSqlQueryTile--table': !onVisualizationChange && !isSavedChart,
            })}
        >
            <Query
                key={queryKey}
                uniqueKey={`SQLEditor-account-sql-${queryKey}`}
                query={visualization ?? node}
                setQuery={
                    onVisualizationChange
                        ? (updated) => {
                              if (updated.kind === NodeKind.DataVisualizationNode) {
                                  onVisualizationChange(updated)
                              }
                          }
                        : undefined
                }
                context={{
                    onLoadingChange: onLoadingChange ? setResultLoading : undefined,
                    externalLoadingIndicator: !!onLoadingChange,
                    dataTableCaptureQueryTelemetry: false,
                    dataTableRenderPlainText: true,
                    insightProps: {
                        dashboardItemId: `new-SQLEditor-account-sql-query-${queryKey}`,
                    },
                }}
                readOnly={!onVisualizationChange}
                embedded={!onVisualizationChange}
            />
        </div>
    )
}
