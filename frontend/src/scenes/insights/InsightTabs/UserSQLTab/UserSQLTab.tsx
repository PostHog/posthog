import React from 'react'
import MonacoEditor from '@monaco-editor/react'

export function UserSQLTab(): JSX.Element {
    return (
        <MonacoEditor
            language="sql"
            height={400}
            onChange={(value) => {
                console.log(value)
            }}
            options={{
                minimap: { enabled: false },
            }}
        />
    )
}
