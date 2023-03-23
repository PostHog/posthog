import { useActions, useValues } from 'kea'
import { HogQLQuery } from '~/queries/schema'
import { useState } from 'react'
import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'
import MonacoEditor from '@monaco-editor/react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { Link } from 'lib/lemon-ui/Link'
import { urls } from 'scenes/urls'

export interface HogQLQueryEditorProps {
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
}

let uniqueNode = 0
export function HogQLQueryEditor(props: HogQLQueryEditorProps): JSX.Element {
    const [key] = useState(() => uniqueNode++)
    const hogQLQueryEditorLogicProps = { query: props.query, setQuery: props.setQuery, key }
    const { queryInput } = useValues(hogQLQueryEditorLogic(hogQLQueryEditorLogicProps))
    const { setQueryInput, saveQuery } = useActions(hogQLQueryEditorLogic(hogQLQueryEditorLogicProps))

    return (
        <div className="space-y-2">
            <div>
                Run SQL queries with{' '}
                <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                    HogQL
                </a>
                , our wrapper around ClickHouse SQL. Explore the <Link to={urls.database()}>database schema</Link>{' '}
                available to you.
            </div>
            <div
                data-attr="hogql-query-editor"
                className={'flex flex-col p-2 bg-border space-y-2 resize-y overflow-auto h-80 w-full'}
            >
                <div className="flex-1">
                    <AutoSizer disableWidth>
                        {({ height }) => (
                            <MonacoEditor
                                theme="vs-light"
                                className="border"
                                language="mysql"
                                value={queryInput}
                                onChange={(v) => setQueryInput(v ?? '')}
                                height={height}
                                options={{
                                    minimap: {
                                        enabled: false,
                                    },
                                    wordWrap: 'on',
                                }}
                                loading={<Spinner />}
                            />
                        )}
                    </AutoSizer>
                </div>
                <LemonButton
                    onClick={saveQuery}
                    type="primary"
                    status={'muted-alt'}
                    disabledReason={!props.setQuery ? 'No permission to update' : undefined}
                    fullWidth
                    center
                >
                    {!props.setQuery ? 'No permission to update' : 'Update'}
                </LemonButton>
            </div>
        </div>
    )
}
