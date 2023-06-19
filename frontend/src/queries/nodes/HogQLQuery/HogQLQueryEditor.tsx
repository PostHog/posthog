import { useActions, useValues } from 'kea'
import { HogQLQuery } from '~/queries/schema'
import { useEffect, useRef, useState } from 'react'
import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'
import MonacoEditor, { Monaco } from '@monaco-editor/react'
import { AutoSizer } from 'react-virtualized/dist/es/AutoSizer'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconInfo } from 'lib/lemon-ui/icons'
import { Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { IDisposable, editor as importedEditor } from 'monaco-editor'

export interface HogQLQueryEditorProps {
    query: HogQLQuery
    setQuery?: (query: HogQLQuery) => void
}

let uniqueNode = 0
export function HogQLQueryEditor(props: HogQLQueryEditorProps): JSX.Element {
    const [key] = useState(() => uniqueNode++)
    const [monacoAndEditor, setMonacoAndEditor] = useState(
        null as [Monaco, importedEditor.IStandaloneCodeEditor] | null
    )
    const [monaco, editor] = monacoAndEditor ?? []
    const hogQLQueryEditorLogicProps = { query: props.query, setQuery: props.setQuery, key, editor, monaco }
    const { queryInput, hasErrors, error } = useValues(hogQLQueryEditorLogic(hogQLQueryEditorLogicProps))
    const { setQueryInput, saveQuery } = useActions(hogQLQueryEditorLogic(hogQLQueryEditorLogicProps))

    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])

    return (
        <div className="space-y-2">
            <div
                data-attr="hogql-query-editor"
                className={'flex flex-col p-2 bg-border space-y-2 resize-y h-80 w-full rounded min-h-60'}
            >
                <div className="relative flex-1">
                    <span className="absolute top-0 right-0 mt-1 mr-1 z-10">
                        <LemonButtonWithDropdown
                            icon={<IconInfo />}
                            type="secondary"
                            size="small"
                            dropdown={{
                                overlay: (
                                    <div>
                                        Run SQL queries with{' '}
                                        <a href="https://posthog.com/manual/hogql" target={'_blank'}>
                                            HogQL
                                        </a>
                                        , our wrapper around ClickHouse SQL. Explore the{' '}
                                        <Link to={urls.database()}>database schema</Link> available to you.
                                    </div>
                                ),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                        />
                    </span>
                    <AutoSizer disableWidth>
                        {({ height }) => (
                            <MonacoEditor
                                theme="vs-light"
                                className="border"
                                language="mysql"
                                value={queryInput}
                                onChange={(v) => setQueryInput(v ?? '')}
                                height={height}
                                onMount={(editor, monaco) => {
                                    monacoDisposables.current.push(
                                        editor.addAction({
                                            id: 'saveAndRunPostHog',
                                            label: 'Save and run query',
                                            keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
                                            run: () => saveQuery(),
                                        })
                                    )
                                    setMonacoAndEditor([monaco, editor])
                                }}
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
                    disabledReason={
                        !props.setQuery
                            ? 'No permission to update'
                            : hasErrors
                            ? error ?? 'Query has errors'
                            : undefined
                    }
                    fullWidth
                    center
                    data-attr="hogql-query-editor-save"
                >
                    {!props.setQuery ? 'No permission to update' : 'Update'}
                </LemonButton>
            </div>
        </div>
    )
}
