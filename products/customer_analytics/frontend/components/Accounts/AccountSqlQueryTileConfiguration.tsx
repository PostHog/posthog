import { LemonLabel } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import {
    ACCOUNT_SQL_QUERY_PLACEHOLDER,
    ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME,
    getAccountSqlQuery,
} from './accountSqlQuery'
import type { AccountViewTileConfigEditorProps } from './accountViewTileConfig'

const PREVIEW_GLOBALS = { [ACCOUNT_SQL_QUERY_PLACEHOLDER_NAME]: '' }

export function AccountSqlQueryTileConfiguration({ config, onChange }: AccountViewTileConfigEditorProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonLabel>SQL query</LemonLabel>
            <p className="m-0 text-xs text-secondary">
                Filter an account ID column in every SELECT's WHERE clause, including subqueries and UNION branches. For
                example: <code>SELECT * FROM system.accounts WHERE external_id = {ACCOUNT_SQL_QUERY_PLACEHOLDER}</code>.
                For warehouse tables, use the column that stores the account's external ID. Every OR branch must keep
                this filter. Use the column directly, without a SELECT or WITH alias.
            </p>
            <CodeEditorResizeable
                language="hogQL"
                globals={PREVIEW_GLOBALS}
                value={getAccountSqlQuery(config)}
                onChange={(value) => onChange({ query: value ?? '' })}
                minHeight="8rem"
                maxHeight="40vh"
            />
        </div>
    )
}
