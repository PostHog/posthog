import { useActions, useValues } from 'kea'
import MonacoEditor, { useMonaco } from '@monaco-editor/react'
import { useEffect, useState } from 'react'
import schema from '~/queries/schema.json'
import { LemonButton } from 'lib/components/LemonButton'
import { queryEditorLogic } from '~/queries/QueryEditor/queryEditorLogic'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import clsx from 'clsx'

export interface QueryEditorProps {
    query: string
    setQuery?: (query: string) => void
    className?: string
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
        <div
            style={{ height: 300 }}
            className={clsx('flex flex-col p-2 bg-border space-y-2 h-full resize-y overflow-auto', props.className)}
        >
            <div className="flex-1">
                <AutoSizer disableWidth>
                    {({ height }) => (
                        <MonacoEditor
                            theme="vs-light"
                            className="border"
                            language="json"
                            value={queryInput}
                            onChange={(v) => setQueryInput(v ?? '')}
                            height={height}
                        />
                    )}
                </AutoSizer>
            </div>
            {error ? (
                <div className="bg-danger text-white p-2">
                    <strong>Error parsing JSON:</strong> {error}
                </div>
            ) : null}
            <LemonButton
                onClick={saveQuery}
                type="primary"
                status={error ? 'danger' : 'muted-alt'}
                disabled={!props.setQuery || !!error || !inputChanged}
                fullWidth
                center
            >
                {!props.setQuery ? 'No permission to update' : 'Update'}
            </LemonButton>
        </div>
    )
}
