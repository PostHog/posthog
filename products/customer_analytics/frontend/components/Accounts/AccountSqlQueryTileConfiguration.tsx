import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { LemonBanner, LemonLabel } from '@posthog/lemon-ui'

import { SQLEditor, SQLEditorPanel } from 'scenes/data-warehouse/editor/SQLEditor'
import { SQLEditorMode } from 'scenes/data-warehouse/editor/sqlEditorModes'

import { ProductKey } from '~/queries/schema/schema-general'

import { ACCOUNT_SQL_QUERY_PLACEHOLDER } from './accountSqlQuery'
import { accountSqlQueryEditorLogic } from './accountSqlQueryEditorLogic'
import { AccountSqlQueryTile } from './AccountSqlQueryTile'
import type { AccountViewTileConfigEditorProps } from './accountViewTileConfig'

export function AccountSqlQueryTileConfiguration(props: AccountViewTileConfigEditorProps): JSX.Element {
    const id = useId()
    const tabId = `account-sql-${props.projectId}-${props.accountId}-${id}`
    const logic = accountSqlQueryEditorLogic({ ...props, tabId })
    const { account, accountLoading, accountLoadFailed, previewConfig, previewRevision } = useValues(logic)
    const { runPreview, setVisualization, loadAccount } = useActions(logic)
    const runDisabledReason = props.saving
        ? 'Saving changes'
        : accountLoading
          ? 'Loading the account'
          : !account?.external_id?.trim()
            ? 'This account needs an external ID before you can preview its query'
            : undefined
    return (
        <div className="flex flex-col gap-2 ph-no-capture">
            <LemonLabel
                info={
                    <>
                        Filter an account ID column in every SELECT's WHERE clause, including subqueries and UNION
                        branches. For example:{' '}
                        <code>SELECT * FROM system.accounts WHERE external_id = {ACCOUNT_SQL_QUERY_PLACEHOLDER}</code>.
                        For warehouse tables, use the column that stores the account's external ID. Every OR branch must
                        keep this filter. Use the column directly, without a SELECT or WITH alias.
                    </>
                }
            >
                SQL query
            </LemonLabel>
            {accountLoadFailed ? (
                <LemonBanner type="error" action={{ children: 'Try again', onClick: () => loadAccount() }}>
                    Could not load the account. Retry to preview this query.
                </LemonBanner>
            ) : null}
            <div className="h-64 min-h-0">
                <SQLEditor
                    tabId={tabId}
                    mode={SQLEditorMode.Embedded}
                    panel={SQLEditorPanel.Query}
                    hostProduct={ProductKey.CUSTOMER_ANALYTICS}
                    defaultShowDatabaseTree={false}
                    autoFocusQueryPane={false}
                    singleStatement
                    hideAgentHints
                    hideVariables
                    hideFilters
                    hideAiTools
                    hideConnectionSelector
                    onRunQuery={runPreview}
                    runQueryDisabledReason={runDisabledReason}
                    runQueryTooltip="Preview for this account"
                />
            </div>
            {previewConfig && account?.external_id ? (
                <div className="min-h-80">
                    <LemonLabel>Preview for this account</LemonLabel>
                    <AccountSqlQueryTile
                        key={previewRevision}
                        accountId={props.accountId}
                        externalId={account.external_id}
                        instanceId={`${tabId}-preview-${previewRevision}`}
                        initialConfig={previewConfig}
                        onVisualizationChange={setVisualization}
                    />
                </div>
            ) : (
                <p className="m-0 text-xs text-secondary">Run the query to preview its results and choose a chart.</p>
            )}
        </div>
    )
}
