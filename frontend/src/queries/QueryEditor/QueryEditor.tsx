import { useMonaco } from '@monaco-editor/react'
import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { CodeEditor } from 'lib/components/CodeEditors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { useEffect, useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { queryEditorLogic } from '~/queries/QueryEditor/queryEditorLogic'
import schema from '~/queries/schema.json'
import { QueryContext } from '~/queries/types'

export interface QueryEditorProps {
    query: string
    setQuery?: (query: string) => void
    className?: string
    context?: QueryContext
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
        <>
            {props.context?.showQueryHelp ? (
                <div className="mb-2 flex flex-row flex-wrap justify-between items-center">
                    <div>Insight configurations follow a declarative schema. Edit them as code here.</div>
                </div>
            ) : null}
            <div
                data-attr="query-editor"
                className={clsx(
                    'flex flex-col p-2 bg-mid space-y-2 resize-y overflow-auto h-80 rounded',
                    props.className
                )}
            >
                <div className="flex-1">
                    <AutoSizer disableWidth>
                        {({ height }) => (
                            <CodeEditor
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
                    status={error ? 'danger' : 'default'}
                    disabled={!props.setQuery || !!error || !inputChanged}
                    fullWidth
                    center
                    data-attr="query-editor-save"
                >
                    {!props.setQuery ? 'No permission to update' : 'Update and run'}
                </LemonButton>
            </div>
        </>
    )
}
