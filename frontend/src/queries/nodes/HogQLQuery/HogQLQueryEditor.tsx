import { useActions, useValues } from 'kea'
import { HogQLQuery } from '~/queries/schema'
import { useState } from 'react'
import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'
import MonacoEditor from '@monaco-editor/react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { LemonButton } from 'lib/lemon-ui/LemonButton'

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
        <div className={'flex flex-col p-2 bg-border space-y-2 resize-y overflow-auto h-80 w-full'}>
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
    )
}
