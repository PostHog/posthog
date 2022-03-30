import React, { useState } from 'react'
import MonacoEditor from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import { userSQLlogic } from 'scenes/userSQL/userSQLlogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/components/LemonButton'

export function UserSQLTab(): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const { setFilters } = useActions(userSQLlogic(insightProps))
    const [query, setQuery] = useState<string | undefined>(filters.user_sql || '')

    const onSubmit = (): void => {
        setFilters({
            user_sql: query,
        })
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
            <LemonButton type="primary" onClick={onSubmit}>
                Run
            </LemonButton>
        </div>
    )
}
