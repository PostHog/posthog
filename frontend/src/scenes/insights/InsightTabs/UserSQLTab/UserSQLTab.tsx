import React, { useState } from 'react'
import MonacoEditor from '@monaco-editor/react'
import { useActions, useValues } from 'kea'
import { userSQLlogic } from 'scenes/userSQL/userSQLlogic'
import { insightLogic } from 'scenes/insights/insightLogic'
import { LemonButton } from 'lib/components/LemonButton'
import { format } from 'sql-formatter'
import { LemonRow } from 'lib/components/LemonRow'
import { useEventListener } from 'lib/hooks/useEventListener'
import { Switch } from 'antd'

export function UserSQLTab(): JSX.Element {
    const { insightProps, filters } = useValues(insightLogic)
    const { loadResultsWithProgress } = useActions(insightLogic)
    const { setFilters } = useActions(userSQLlogic(insightProps))
    const [query, setQuery] = useState<string | undefined>(format(filters.user_sql || ''))
    const [theme, setTheme] = useState('light')

    useEventListener('keydown', (event) => {
        if (event.key === 'Enter' && (event.ctrlKey || event.metaKey)) {
            event.preventDefault()
            onSubmit()
        }
    })

    const onSubmit = (): void => {
        if (query !== filters.user_sql) {
            setFilters({
                user_sql: query,
            })
        }
        loadResultsWithProgress()
    }

    const onFormat = (): void => {
        setQuery(format(query || ''))
    }

    return (
        <div>
            <Switch
                checkedChildren="dark"
                unCheckedChildren="light"
                style={{ marginBottom: 8, float: 'right' }}
                onChange={() => {
                    const newTheme = theme === 'light' ? 'vs-dark' : 'light'
                    setTheme(newTheme)
                }}
            />
            <MonacoEditor
                language="sql"
                height={400}
                theme={theme}
                value={query}
                onChange={(value) => {
                    setQuery(value)
                }}
                options={{
                    minimap: { enabled: false },
                    renderLineHighlight: 'none',
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
