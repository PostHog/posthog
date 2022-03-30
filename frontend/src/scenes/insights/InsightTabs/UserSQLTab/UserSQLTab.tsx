import React, { useState } from 'react'
import MonacoEditor from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import { userSQLlogic } from 'scenes/userSQL/userSQLlogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { format } from 'sql-formatter'
import { LemonRow } from 'lib/components/LemonRow'

export function UserSQLTab(): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const { setFilters } = useActions(userSQLlogic(insightProps))
    const [query, setQuery] = useState<string | undefined>(filters.user_sql || '')

    const onSubmit = (): void => {
        setFilters({
            user_sql: query,
        })
    }

    const onFormat = (): void => {
        setQuery(format(query || ''))
    }

    return (
        <div>
            <MonacoEditor
                language="sql"
                height={400}
                value={query}
                onChange={(value) => {
                    setQuery(value)
                }}
                options={{
                    minimap: { enabled: false },
                }}
            />
            <LemonRow>
                <LemonButton style={{ marginRight: 8 }} type="primary" onClick={onFormat}>
                    Format
                </LemonButton>
                <LemonButton type="primary" onClick={onSubmit}>
                    Run
                </LemonButton>
            </LemonRow>
        </div>
    )
}
