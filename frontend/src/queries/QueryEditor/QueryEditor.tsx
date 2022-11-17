import { useActions, useValues } from 'kea'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect, useState } from 'react'
import schema from '~/queries/nodes.json'
import { LemonButton } from 'lib/components/LemonButton'
import { queryEditorLogic } from '~/queries/QueryEditor/queryEditorLogic'

export interface QueryEditorProps {
    query: string
    setQuery?: (query: string) => void
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
                    uri: 'https://internal.posthog.com/node-schema.json',
                    fileMatch: ['*'], // associate with our model
                    schema: schema,
                },
            ],
        })
    }, [monaco])

    return (
        <div className="flex flex-col space-y-2">
            <MonacoEditor
                theme="vs-light"
                className="border"
                language={'json'}
                value={queryInput}
                onChange={(v) => setQueryInput(v ?? '')}
                height={300}
            />
            <div className="flex flex-row items-center space-x-2">
                <LemonButton
                    onClick={() => saveQuery()}
                    type="primary"
                    status={error ? 'danger' : 'primary'}
                    disabled={!props.setQuery || !!error || !inputChanged}
                >
                    Update
                </LemonButton>
                {error ? (
                    <div className="text-danger">
                        <strong>Error parsing JSON:</strong> {error}
                    </div>
                ) : null}
            </div>
        </div>
    )
}
