import { useActions, useValues } from 'kea'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect, useState } from 'react'
import schema from '~/queries/schema.json'
import { LemonButton } from 'lib/components/LemonButton'
import { queryEditorLogic } from '~/queries/QueryEditor/queryEditorLogic'

export interface QueryEditorProps {
    query: string
    setQuery?: (query: string) => void
    height?: number
}

let i = 0
export function QueryEditor(props: QueryEditorProps): JSX.Element {
    const [key] = useState(() => i++)
    const { queryInput, error, inputChanged } = useValues(queryEditorLogic({ ...props, key }))
    const { setQueryInput, saveQuery } = useActions(queryEditorLogic({ ...props, key }))
    const monaco = useMonaco()

    useEffect(() => {
        if (!monaco) {
            return
        }
        monaco.languages.json.jsonDefaults.setDiagnosticsOptions({
            validate: true,
            schemas: [
                {
                    uri: 'http://internal/node-schema.json',
                    fileMatch: ['*'], // associate with our model
                    schema: schema,
                },
            ],
        })
    }, [monaco])

    return (
        <div className="p-2 bg-border space-y-2">
            <MonacoEditor
                theme="vs-light"
                className="border"
                language="json"
                value={queryInput}
                onChange={(v) => setQueryInput(v ?? '')}
                height={props.height ?? 300}
            />
            {error ? (
                <div className="bg-danger text-white p-2">
                    <strong>Error parsing JSON:</strong> {error}
                </div>
            ) : null}
            <LemonButton
                onClick={() => saveQuery()}
                type="primary"
                status={error ? 'danger' : 'muted-alt'}
                disabled={!props.setQuery || !!error || !inputChanged}
                fullWidth
                center
            >
                Update
            </LemonButton>
        </div>
    )
}
