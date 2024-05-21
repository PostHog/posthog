import clsx from 'clsx'
import { BindLogic, useValues } from 'kea'
import { CodeEditor } from 'lib/components/CodeEditors'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import type { IDisposable } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'

import { dataNodeLogic, DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { HogQuery, HogQueryResponse } from '~/queries/schema'

export interface HogQueryEditorProps {
    query: HogQuery
    setQuery?: (query: HogQuery) => void
}

export function HogQueryEditor(props: HogQueryEditorProps): JSX.Element {
    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    }, [])
    const [queryInput, setQueryInput] = useState(props.query.code)
    useEffect(() => {
        setQueryInput(props.query?.code)
    }, [props.query?.code])

    function saveQuery(): void {
        if (props.setQuery) {
            props.setQuery({ ...props.query, code: queryInput })
        }
    }

    return (
        <div className="space-y-2">
            <div data-attr="hogql-query-editor" className={clsx('flex flex-col rounded space-y-2 w-full p-2 border')}>
                <div className="relative flex-1 overflow-hidden">
                    {/* eslint-disable-next-line react/forbid-dom-props */}
                    <div className="resize-y overflow-hidden" style={{ height: 222 }}>
                        <CodeEditor
                            className="border rounded overflow-hidden h-full"
                            language="rust"
                            value={queryInput}
                            onChange={(v) => setQueryInput(v ?? '')}
                            height="100%"
                            onMount={(editor, monaco) => {
                                monacoDisposables.current.push(
                                    editor.addAction({
                                        id: 'saveAndRunPostHog',
                                        label: 'Save and run query',
                                        keybindings: [monaco.KeyMod.CtrlCmd | monaco.KeyCode.Enter],
                                        run: () => saveQuery(),
                                    })
                                )
                            }}
                            options={{
                                minimap: {
                                    enabled: false,
                                },
                                wordWrap: 'on',
                                scrollBeyondLastLine: false,
                                automaticLayout: true,
                                fixedOverflowWidgets: true,
                                suggest: {
                                    showInlineDetails: true,
                                },
                                quickSuggestionsDelay: 300,
                            }}
                        />
                    </div>
                </div>
                <div className="flex flex-row">
                    <div className="flex-1">
                        <LemonButton
                            onClick={saveQuery}
                            type="primary"
                            disabledReason={!props.setQuery ? 'No permission to update' : undefined}
                            center
                            fullWidth
                            data-attr="hogql-query-editor-save"
                        >
                            {!props.setQuery ? 'No permission to update' : 'Update and run'}
                        </LemonButton>
                    </div>
                </div>
            </div>
        </div>
    )
}

interface HogDebugProps {
    queryKey: string
    query: HogQuery
    setQuery?: (query: HogQuery) => void
    debug?: boolean
}

export function HogDebug({ query, setQuery, queryKey, debug }: HogDebugProps): JSX.Element {
    const dataNodeLogicProps: DataNodeLogicProps = { query, key: queryKey, dataNodeCollectionId: queryKey }
    const { dataLoading, response: _response } = useValues(dataNodeLogic(dataNodeLogicProps))
    const response = _response as HogQueryResponse | null
    const [tab, setTab] = useState('results' as 'results' | 'bytecode' | 'stdout')

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div className="space-y-2">
                {setQuery ? (
                    <>
                        <HogQueryEditor query={query} setQuery={setQuery} />
                        <LemonDivider className="my-4" />
                        <div className="flex gap-2">
                            <Reload />
                        </div>
                    </>
                ) : null}
                {dataLoading ? (
                    <>
                        <h2>Running query...</h2>
                        <div className="flex">
                            Time elapsed:&nbsp;
                            <ElapsedTime />
                        </div>
                    </>
                ) : (
                    <>
                        {debug ? (
                            <LemonTabs
                                tabs={[
                                    { label: 'Results', key: 'results' },
                                    { label: 'Stdout', key: 'stdout' },
                                    { label: 'Bytecode', key: 'bytecode' },
                                ]}
                                activeKey={tab}
                                onChange={(key) => setTab(String(key) as 'results' | 'bytecode')}
                            />
                        ) : null}
                        {tab === 'bytecode' && debug ? (
                            <CodeEditor
                                className="border"
                                language="json"
                                value={
                                    response?.bytecode
                                        ? JSON.stringify(response?.bytecode)
                                        : 'No bytecode returned with response'
                                }
                                height={500}
                                path={`debug/${queryKey}/hog-bytecode.json`}
                                options={{ wordWrap: 'on' }}
                            />
                        ) : tab === 'stdout' ? (
                            <CodeEditor
                                className="border"
                                language="text"
                                value={String(response?.stdout ?? 'No bytecode returned with response')}
                                height={500}
                                path={`debug/${queryKey}/hog-stdout.txt`}
                                options={{ wordWrap: 'on' }}
                            />
                        ) : (
                            <CodeEditor
                                className="border"
                                language={typeof response?.results === 'object' ? 'json' : 'text'}
                                value={
                                    typeof response?.results === 'object'
                                        ? JSON.stringify(response?.results ?? '', null, 2)
                                        : String(response?.results ?? '')
                                }
                                height={500}
                                path={`debug/${queryKey}/hog-result.json`}
                            />
                        )}
                    </>
                )}
            </div>
        </BindLogic>
    )
}
