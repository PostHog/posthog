import { printHogStringOutput } from '@posthog/hogvm'
import { IconPlus, IconTrash } from '@posthog/icons'
import { LemonButton, LemonTable, LemonTabs } from '@posthog/lemon-ui'
import { useActions, useValues } from 'kea'
import { JSONViewer } from 'lib/components/JSONViewer'
import { CodeEditor } from 'lib/monaco/CodeEditor'
import { CodeEditorInline } from 'lib/monaco/CodeEditorInline'
import React, { useState } from 'react'
import { SceneExport } from 'scenes/sceneTypes'

import { renderHogQLX } from '~/queries/nodes/HogQLX/render'

import { hogReplLogic, isTreeFileNode, ReplChunk as ReplChunkType, TreeNode } from './hogReplLogic'

export interface ReplResultsTableProps {
    response: {
        results: any[][]
        columns: string[]
    }
}

export function ReplResultsTable({ response }: ReplResultsTableProps): JSX.Element {
    const [activeTab, setActiveTab] = useState<'table' | 'json'>('table')
    return (
        <div>
            <LemonTabs
                activeKey={activeTab}
                onChange={setActiveTab as any}
                tabs={[
                    {
                        key: 'table',
                        label: 'Table',
                        content: (
                            <LemonTable
                                columns={response.columns.map((col, index) => ({ dataIndex: index, title: col }))}
                                dataSource={response.results}
                            />
                        ),
                    },
                    {
                        key: 'json',
                        label: 'JSON',
                        content: <JSONViewer name={false} src={response} />,
                    },
                    {
                        key: 'raw',
                        label: 'Raw',
                        content: <div>{printHogStringOutput(response)}</div>,
                    },
                ]}
            />
        </div>
    )
}

function printRichHogOutput(arg: any): JSX.Element | string {
    if (typeof arg === 'object' && arg !== null) {
        if ('__hx_tag' in arg) {
            return renderHogQLX(arg)
        }
        if ('results' in arg && 'columns' in arg && Array.isArray(arg.results) && Array.isArray(arg.columns)) {
            return <ReplResultsTable response={arg} />
        }
    }
    return printHogStringOutput(arg)
}

function extensionToLanguage(ext: string): string {
    return { ts: 'typescript', tsx: 'typescript' }[ext] ?? ext
}

interface ReplChunkProps {
    chunk: ReplChunkType
    editFromHere: () => void
}

export function ReplChunk({
    chunk: { code, result, print, error, status },
    editFromHere,
}: ReplChunkProps): JSX.Element {
    return (
        <div className="pb-2 border-b border-gray-300">
            <LemonButton size="small" type="secondary" className="float-right" onClick={editFromHere}>
                📝
            </LemonButton>
            <div className="flex items-start">
                <span
                    // eslint-disable-next-line react/forbid-dom-props
                    style={{ color: 'blue' }}
                >
                    {'>'}
                </span>
                <div className="flex-1 whitespace-pre-wrap ml-2">{code}</div>
            </div>
            {status === 'pending' && (
                <div className="flex items-center ml-4 mt-2">
                    <svg
                        className="animate-spin h-5 w-5 text-gray-500 mr-2"
                        xmlns="http://www.w3.org/2000/svg"
                        fill="none"
                        viewBox="0 0 24 24"
                    >
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8z" />
                    </svg>
                </div>
            )}
            {print && Array.isArray(print) ? (
                <div className="flex items-start mt-2">
                    <span
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: 'green' }}
                    >
                        #
                    </span>
                    <div className="flex-1 whitespace-pre-wrap ml-2">
                        {print.map((line, index) => (
                            <div key={index}>
                                {line.map((arg, argIndex) => (
                                    <React.Fragment key={argIndex}>
                                        {printRichHogOutput(arg)}
                                        {argIndex < line.length - 1 ? ' ' : ''}
                                    </React.Fragment>
                                ))}
                            </div>
                        ))}
                    </div>
                </div>
            ) : null}
            {status === 'success' && result !== undefined && (
                <div className="flex items-start mt-2">
                    <span
                        // eslint-disable-next-line react/forbid-dom-props
                        style={{ color: 'green' }}
                    >
                        {'<'}
                    </span>
                    <div className="flex-1 whitespace-pre-wrap ml-2">{printRichHogOutput(result)}</div>
                </div>
            )}
            {status === 'error' && (
                <div className="flex items-start mt-2">
                    <span className="text-danger">!</span>
                    <div className="flex-1 whitespace-pre-wrap ml-2 text-danger">{error}</div>
                </div>
            )}
        </div>
    )
}

export function HogRepl(): JSX.Element {
    const { fileTree, replChunks, currentCode, currentFile, lastLocalGlobals } = useValues(hogReplLogic)
    const { runCurrentCode, setCurrentCode, editFromHere, setCurrentFile, newFile, deleteFile } =
        useActions(hogReplLogic)

    function printTree(fileTree: TreeNode, pastPath: string[]): JSX.Element {
        return (
            <>
                {Object.entries(fileTree).map(([key, subTree]) => {
                    const fullPath = [...pastPath, key].join('/')
                    return isTreeFileNode(subTree) ? (
                        <div key={key} className="flex w-full justify-between">
                            <LemonButton
                                size="small"
                                active={fullPath === currentFile}
                                className="font-mono"
                                onClick={() => setCurrentFile(fullPath)}
                            >
                                {key}
                            </LemonButton>
                            <LemonButton size="xsmall" icon={<IconTrash />} onClick={() => deleteFile(fullPath)} />
                        </div>
                    ) : (
                        <React.Fragment key={key}>
                            <div className="flex w-full justify-between">
                                <LemonButton size="small" className="font-mono">
                                    {key}/
                                </LemonButton>
                                <LemonButton size="xsmall" icon={<IconPlus />} onClick={() => newFile(fullPath)} />
                            </div>
                            <div className="pl-2">{printTree(subTree, [...pastPath, key])}</div>
                        </React.Fragment>
                    )
                })}
            </>
        )
    }

    return (
        <div
            className="flex w-full gap-2"
            // eslint-disable-next-line react/forbid-dom-props
            style={{ height: 'calc(100vh - 100px)' }}
        >
            <div className="w-[20%] min-w-[175px] max-w-[400px]">{printTree(fileTree, [])}</div>
            {currentFile.endsWith('.hog') ? (
                <div className="p-4 bg-white text-black font-mono w-full">
                    <div className="space-y-4">
                        {replChunks.map((chunk, index) => (
                            <ReplChunk chunk={chunk} key={index} editFromHere={() => editFromHere(index)} />
                        ))}
                        <div className="flex items-start">
                            <span
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ color: 'blue' }}
                            >
                                {'>'}
                            </span>
                            <div
                                className="w-full"
                                // eslint-disable-next-line react/forbid-dom-props
                                style={{ marginLeft: -10, marginTop: -7, marginRight: -5, marginBottom: -5 }}
                            >
                                <CodeEditorInline
                                    language="hog"
                                    embedded
                                    className="flex-1 bg-transparent focus:outline-none resize-none ml-2 p-0"
                                    value={currentCode}
                                    onChange={(value) => setCurrentCode(value ?? '')}
                                    onPressCmdEnter={runCurrentCode}
                                    onPressUpNoValue={() => {
                                        if ((hogReplLogic.findMounted()?.values.replChunks.length ?? 0) > 0) {
                                            editFromHere(replChunks.length - 1)
                                        }
                                    }}
                                    options={{ fontSize: 14, padding: { top: 0, bottom: 0 } }}
                                    globals={lastLocalGlobals}
                                    autoFocus
                                />
                            </div>
                            <LemonButton size="small" type="primary" onClick={runCurrentCode}>
                                ⌘⏎
                            </LemonButton>
                        </div>
                    </div>
                </div>
            ) : (
                <CodeEditor
                    language={extensionToLanguage(currentFile.split('.').pop() ?? 'hog')}
                    className="flex-1 bg-transparent focus:outline-none resize-none ml-2 p-0 min-h-[300px]"
                    value={currentCode}
                    onChange={(value) => setCurrentCode(value ?? '')}
                    options={{ fontSize: 14, padding: { top: 0, bottom: 0 } }}
                    autoFocus
                />
            )}
        </div>
    )
}

export const scene: SceneExport = {
    component: HogRepl,
    logic: hogReplLogic,
}
