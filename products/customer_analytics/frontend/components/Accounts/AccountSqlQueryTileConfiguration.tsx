import { LemonLabel } from '@posthog/lemon-ui'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { ACCOUNT_SQL_QUERY_PLACEHOLDER, getAccountSqlQuery } from './accountSqlQuery'
import type { AccountViewTileConfigEditorProps } from './accountViewTileConfig'

export function AccountSqlQueryTileConfiguration({ config, onChange }: AccountViewTileConfigEditorProps): JSX.Element {
    return (
        <div className="flex flex-col gap-1">
            <LemonLabel>SQL query</LemonLabel>
            <p className="m-0 text-xs text-secondary">
                Use {ACCOUNT_SQL_QUERY_PLACEHOLDER} where the account's ID goes. Each account shows only its own rows,
                for example: <code>where organization_id = {ACCOUNT_SQL_QUERY_PLACEHOLDER}</code>
            </p>
            <CodeEditorResizeable
                language="hogQL"
                value={getAccountSqlQuery(config)}
                onChange={(value) => onChange({ query: value ?? '' })}
                minHeight="8rem"
                maxHeight="40vh"
            />
        </div>
    )
}
