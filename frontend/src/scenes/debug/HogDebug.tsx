import clsx from 'clsx'
import { BindLogic, BuiltLogic, LogicWrapper, useValues } from 'kea'
import type { IDisposable } from 'monaco-editor'
import { useEffect, useRef, useState } from 'react'

import { useOnMountEffect } from 'lib/hooks/useOnMountEffect'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonDivider } from 'lib/lemon-ui/LemonDivider'
import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { useAttachedLogic } from 'lib/logic/scenes/useAttachedLogic'
import { CodeEditor } from 'lib/monaco/CodeEditor'

import { ElapsedTime } from '~/queries/nodes/DataNode/ElapsedTime'
import { Reload } from '~/queries/nodes/DataNode/Reload'
import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { HogQLQueryModifiers, HogQuery, HogQueryResponse } from '~/queries/schema/schema-general'

export interface HogQueryEditorProps {
    query: HogQuery
    setQuery?: (query: HogQuery) => void
    queryKey?: string
}

let uniqueNode = 0

export function HogQueryEditor(props: HogQueryEditorProps): JSX.Element {
    // Using useRef, not useState, as we don't want to reload the component when this changes.
    const monacoDisposables = useRef([] as IDisposable[])
    useOnMountEffect(() => {
        return () => {
            monacoDisposables.current.forEach((d) => d?.dispose())
        }
    })

    const [queryInput, setQueryInput] = useState(props.query.code)
    useEffect(() => {
        setQueryInput(props.query?.code)
    }, [props.query?.code])

    const [realKey] = useState(() => uniqueNode++)

    function saveQuery(): void {
        if (props.setQuery) {
            props.setQuery({ ...props.query, code: queryInput })
        }
    }

    return (
        <div className="deprecated-space-y-2">
            <div
                data-attr="hogql-query-editor"
                className={clsx('flex flex-col rounded deprecated-space-y-2 w-full p-2 border')}
            >
                <div className="relative flex-1 overflow-hidden">
                    <div className="resize-y overflow-hidden h-[222px]">
                        <CodeEditor
                            queryKey={props.queryKey ?? `new/${realKey}`}
                            className="border rounded overflow-hidden h-full"
                            language="hog"
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
    setQuery: (query: HogQuery) => void
    debug?: boolean
    modifiers?: HogQLQueryModifiers
    attachTo?: LogicWrapper | BuiltLogic
}

export function HogDebug({ query, setQuery, queryKey, debug, modifiers, attachTo }: HogDebugProps): JSX.Element {
    const dataNodeLogicProps: DataNodeLogicProps = {
        query,
        key: queryKey,
        dataNodeCollectionId: queryKey,
        modifiers,
    }
    const { dataLoading, response: _response } = useValues(dataNodeLogic(dataNodeLogicProps))
    useAttachedLogic(dataNodeLogic(dataNodeLogicProps), attachTo)
    const response = _response as HogQueryResponse | null
    const [tab, setTab] = useState('results' as 'results' | 'bytecode' | 'coloredBytecode' | 'stdout')

    return (
        <BindLogic logic={dataNodeLogic} props={dataNodeLogicProps}>
            <div className="deprecated-space-y-2">
                {setQuery ? (
                    <>
                        <HogQueryEditor query={query} setQuery={setQuery} queryKey={queryKey} />
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
                                    { label: 'Bytecode', key: 'coloredBytecode' },
                                    { label: 'Raw bytecode', key: 'bytecode' },
                                ]}
                                activeKey={tab}
                                onChange={(key) => setTab(String(key) as any)}
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
                        ) : tab === 'coloredBytecode' && debug ? (
                            <CodeEditor
                                className="border"
                                language="swift"
                                value={
                                    response?.coloredBytecode && Array.isArray(response?.coloredBytecode)
                                        ? response?.coloredBytecode
                                              .map((a) => (a.startsWith('op.') ? a : `    ${a}`))
                                              .join('\n')
                                        : 'No bytecode returned with response'
                                }
                                height={500}
                                path={`debug/${queryKey}/hog-bytecode.json`}
                                options={{ wordWrap: 'on', lineNumbers: (nr) => String(nr - 1) }}
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
                                options={{ wordWrap: 'on' }}
                            />
                        )}
                    </>
                )}
            </div>
        </BindLogic>
    )
}
