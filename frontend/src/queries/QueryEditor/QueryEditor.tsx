import clsx from 'clsx'
import { useActions, useValues } from 'kea'
import { useState } from 'react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Link } from 'lib/lemon-ui/Link'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { urls } from 'scenes/urls'

import { queryEditorLogic } from '~/queries/QueryEditor/queryEditorLogic'
import schema from '~/queries/schema.json'
import { QueryContext } from '~/queries/types'

export interface QueryEditorProps {
    query: string
    setQuery?: (query: string) => void
    className?: string
    aboveButton?: JSX.Element
    context?: QueryContext
}

let i = 0

export function QueryEditor(props: QueryEditorProps): JSX.Element {
    const [key] = useState(() => i++)
    const { queryInput, error, inputChanged } = useValues(queryEditorLogic({ ...props, key }))
    const { setQueryInput, saveQuery } = useActions(queryEditorLogic({ ...props, key }))

    return (
        <>
            {props.context?.showQueryHelp ? (
                <div className="mb-2 flex flex-row flex-wrap justify-between items-center">
                    <div>
                        Insight configurations follow a declarative schema. Edit them as code here. Open under{' '}
                        <Link to={urls.debugQuery(queryInput)}>/debug</Link>.
                    </div>
                </div>
            ) : null}
            <div
                data-attr="query-editor"
                className={clsx(
                    'flex flex-col p-2 bg-primary deprecated-space-y-2 resize-y overflow-auto min-h-80 rounded',
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
                                schema={schema}
                            />
                        )}
                    </AutoSizer>
                </div>
                {error ? (
                    <div className="bg-danger text-white p-2">
                        <strong>Error parsing JSON:</strong> {error}
                    </div>
                ) : null}
                {props.aboveButton}
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
