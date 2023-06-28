import { useActions, useValues } from 'kea'
import { HogQLQuery } from '~/queries/schema'
import { useEffect, useRef, useState } from 'react'
import { hogQLQueryEditorLogic } from './hogQLQueryEditorLogic'
import MonacoEditor, { Monaco } from '@monaco-editor/react'
import { LemonButton, LemonButtonWithDropdown } from 'lib/lemon-ui/LemonButton'
import { Spinner } from 'lib/lemon-ui/Spinner'
import { IconAutoAwesome, IconErrorOutline, IconInfo } from 'lib/lemon-ui/icons'
import { LemonInput, Link } from '@posthog/lemon-ui'
import { urls } from 'scenes/urls'
import { IDisposable, editor as importedEditor } from 'monaco-editor'
import { themeLogic } from '~/layout/navigation-3000/themeLogic'

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
    const { queryInput, hasErrors, error, prompt, promptError, promptLoading } = useValues(
        hogQLQueryEditorLogic(hogQLQueryEditorLogicProps)
    )
    const { setQueryInput, saveQuery, setPrompt, draftFromPrompt } = useActions(
        hogQLQueryEditorLogic(hogQLQueryEditorLogicProps)
    )
    const { isDarkModeOn } = useValues(themeLogic)

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
                className={'flex flex-col p-2 border rounded bg-bg-light space-y-2 resize-y w-full'}
            >
                <div className="flex gap-2">
                    <LemonInput
                        className="grow"
                        prefix={<IconAutoAwesome />}
                        value={prompt}
                        onPressEnter={() => draftFromPrompt()}
                        onChange={(value) => setPrompt(value)}
                        placeholder="What would you like to know?"
                    />
                    <LemonButton
                        type="primary"
                        onClick={() => draftFromPrompt()}
                        disabledReason={!prompt ? 'Provide a prompt first' : null}
                        loading={promptLoading}
                    >
                        Think
                    </LemonButton>
                </div>
                {promptError ? (
                    <div className="text-danger flex items-center gap-1 text-sm">
                        <IconErrorOutline className="text-xl mr-2" />
                        {promptError}
                    </div>
                ) : null}
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
                                        <Link to={urls.dataWarehouse()}>database schema</Link> available to you.
                                    </div>
                                ),
                                placement: 'right-start',
                                fallbackPlacements: ['left-start'],
                                actionable: true,
                                closeParentPopoverOnClickInside: true,
                            }}
                        />
                    </span>
                    <MonacoEditor
                        theme={isDarkModeOn ? 'vs-dark' : 'light'}
                        className="py-2 border rounded overflow-hidden"
                        language="mysql"
                        value={queryInput}
                        onChange={(v) => setQueryInput(v ?? '')}
                        height={234} // 12 lines without scrolling
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
                            scrollBeyondLastLine: false,
                        }}
                        loading={<Spinner />}
                    />
                </div>
                <LemonButton
                    onClick={saveQuery}
                    type="primary"
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
                    {!props.setQuery ? 'No permission to update' : 'Update and run'}
                </LemonButton>
            </div>
        </div>
    )
}
