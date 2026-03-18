import clsx from 'clsx'
import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useLayoutEffect, useMemo, useRef } from 'react'
import { useDebouncedCallback } from 'use-debounce'

import { IconCornerDownRight } from '@posthog/icons'

import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { NotebookDataframeTable } from './components/NotebookDataframeTable'
import { getCellLabel } from './components/NotebookNodeTitle'
import { notebookNodeLogic } from './notebookNodeLogic'
import { PythonExecutionMedia, PythonExecutionResult } from './pythonExecution'
import { buildMediaSource, renderAnsiText } from './utils'

export type NotebookNodeHogQLAttributes = {
    code: string
    returnVariable: string
    hogqlExecution?: PythonExecutionResult | null
    hogqlExecutionCodeHash?: number | null
    hogqlExecutionSandboxId?: string | null
    showSettings?: boolean
}

const OutputBlock = ({
    title,
    className,
    toneClassName,
    value,
}: {
    title: string
    className: string
    toneClassName: string
    value: string
}): JSX.Element => {
    const content = useMemo(() => renderAnsiText(value), [value])

    return (
        <div className={className}>
            <div className="text-[10px] uppercase tracking-wide text-muted">{title}</div>
            <pre
                className={clsx('text-xs font-mono whitespace-pre-wrap mt-1 select-text cursor-text', toneClassName)}
                contentEditable={false}
            >
                {content}
            </pre>
        </div>
    )
}

const MediaBlock = ({ media }: { media: PythonExecutionMedia }): JSX.Element | null => {
    const source = buildMediaSource(media)
    if (!source) {
        return null
    }

    return (
        <div>
            <div className="text-[10px] uppercase tracking-wide text-muted">Image</div>
            <img
                src={source}
                alt="SQL (HogQL) output"
                className="mt-2 max-w-full border border-border rounded bg-bg-light"
            />
        </div>
    )
}

const DEFAULT_HOGQL_SQL_NODE_HEIGHT = 100

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeHogQLAttributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const {
        dataframePage,
        dataframePageSize,
        dataframeLoading,
        dataframeResult,
        dataframeVariableName,
        hogqlReturnVariableUsage,
        expanded,
    } = useValues(nodeLogic)
    const { navigateToNode, setDataframePage, setDataframePageSize } = useActions(nodeLogic)
    const outputRef = useRef<HTMLDivElement | null>(null)
    const footerRef = useRef<HTMLDivElement | null>(null)
    const lastAutoHeightRef = useRef<number | null>(null)
    const lastExecutionCodeHashRef = useRef<number | null>(null)

    const hogqlExecution = attributes.hogqlExecution ?? null
    const hasResult = hogqlExecution?.result !== undefined && hogqlExecution?.result !== null
    const hasExecution =
        hogqlExecution &&
        (hogqlExecution.stdout ||
            hogqlExecution.stderr ||
            hasResult ||
            hogqlExecution.media?.length ||
            hogqlExecution.traceback?.length)
    const executionCodeHash = attributes.hogqlExecutionCodeHash ?? null

    const debouncedUpdateHeight = useDebouncedCallback((height: number) => {
        updateAttributes({ height })
        lastAutoHeightRef.current = height
    }, 150)

    useEffect(() => {
        return () => {
            debouncedUpdateHeight.cancel()
        }
    }, [debouncedUpdateHeight])

    useLayoutEffect(() => {
        if (!hasExecution) {
            return
        }
        const output = outputRef.current
        if (!output) {
            return
        }
        const footerHeight = footerRef.current?.offsetHeight ?? 0
        const desiredHeight = output.scrollHeight + footerHeight + 8
        const currentHeight = typeof attributes.height === 'number' ? attributes.height : DEFAULT_HOGQL_SQL_NODE_HEIGHT
        const lastExecutionCodeHash = lastExecutionCodeHashRef.current
        const executionChanged = executionCodeHash !== lastExecutionCodeHash

        if (executionChanged) {
            lastExecutionCodeHashRef.current = executionCodeHash
            lastAutoHeightRef.current = currentHeight
        }

        const lastAutoHeight = lastAutoHeightRef.current
        const hasManualResize =
            !executionChanged &&
            lastAutoHeight !== null &&
            typeof currentHeight === 'number' &&
            currentHeight < lastAutoHeight

        if (hasManualResize) {
            return
        }

        if (desiredHeight !== currentHeight) {
            debouncedUpdateHeight(desiredHeight)
        }
    }, [
        attributes.height,
        dataframeLoading,
        dataframePageSize,
        dataframeResult,
        executionCodeHash,
        hasExecution,
        debouncedUpdateHeight,
        hogqlExecution?.media?.length,
        hogqlExecution?.result,
        hogqlExecution?.stderr,
        hogqlExecution?.stdout,
        hogqlExecution?.traceback?.length,
    ])

    const isSettingsVisible = attributes.showSettings ?? false
    const showReturnVariableRow = expanded || isSettingsVisible
    const showDataframeTable = !!dataframeVariableName

    const usageLabel = (nodeType: NotebookNodeType, nodeIndex: number | undefined, title: string): string => {
        const trimmedTitle = title.trim()
        if (trimmedTitle) {
            return trimmedTitle
        }
        return getCellLabel(nodeIndex, nodeType) ?? 'SQL'
    }

    if (!expanded && !showReturnVariableRow) {
        return null
    }

    return (
        <div data-attr="notebook-node-hogql-sql" className="flex h-full flex-col">
            {expanded ? (
                <div
                    ref={outputRef}
                    className="space-y-3"
                    onMouseDown={(event) => event.stopPropagation()}
                    onDragStart={(event) => event.stopPropagation()}
                >
                    {hasExecution ? (
                        <>
                            {hogqlExecution?.stdout ? (
                                <OutputBlock
                                    title="Output"
                                    className="p-2"
                                    toneClassName="text-default"
                                    value={hogqlExecution.stdout ?? ''}
                                />
                            ) : null}
                            {hogqlExecution?.stderr ? (
                                <OutputBlock
                                    title="stderr"
                                    className="p-2"
                                    toneClassName="text-danger"
                                    value={hogqlExecution.stderr ?? ''}
                                />
                            ) : null}
                            {hasResult && !showDataframeTable ? (
                                <OutputBlock
                                    title="Result"
                                    className="p-2"
                                    toneClassName="text-default"
                                    value={hogqlExecution.result ?? ''}
                                />
                            ) : null}
                            {showDataframeTable ? (
                                <NotebookDataframeTable
                                    result={dataframeResult}
                                    loading={dataframeLoading}
                                    page={dataframePage}
                                    pageSize={dataframePageSize}
                                    onNextPage={() => setDataframePage(dataframePage + 1)}
                                    onPreviousPage={() => setDataframePage(Math.max(1, dataframePage - 1))}
                                    onPageSizeChange={setDataframePageSize}
                                />
                            ) : null}
                            {hogqlExecution?.media?.map((media, index) => (
                                <MediaBlock key={`hogql-sql-media-${index}`} media={media} />
                            ))}
                            {hogqlExecution?.status === 'error' && hogqlExecution.traceback?.length ? (
                                <OutputBlock
                                    title="Error"
                                    className="p-2"
                                    toneClassName="text-danger"
                                    value={hogqlExecution.traceback.join('\n')}
                                />
                            ) : null}
                        </>
                    ) : (
                        <div className="text-xs text-muted font-mono p-2">Run the query to see execution results.</div>
                    )}
                </div>
            ) : null}
            {showReturnVariableRow ? (
                <div
                    ref={footerRef}
                    className="flex flex-col gap-2 text-xs text-muted border-t p-2"
                    onClick={(event) => event.stopPropagation()}
                    onMouseDown={(event) => event.stopPropagation()}
                >
                    <div className="flex items-center gap-2">
                        <span className="font-mono mt-0.5">
                            <IconCornerDownRight />
                        </span>
                        <input
                            type="text"
                            className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default focus:outline-none focus:ring-1 focus:ring-primary"
                            value={attributes.returnVariable ?? ''}
                            onChange={(event) => updateAttributes({ returnVariable: event.target.value })}
                            spellCheck={false}
                        />
                        {hogqlReturnVariableUsage.length > 0 ? (
                            <span className="text-muted">
                                Used in{' '}
                                {hogqlReturnVariableUsage.map((usage) => (
                                    <button
                                        key={usage.nodeId}
                                        type="button"
                                        className="text-muted hover:text-default underline underline-offset-2 ml-1"
                                        onClick={() => navigateToNode(usage.nodeId)}
                                    >
                                        {usageLabel(usage.nodeType, usage.nodeIndex, usage.title)}
                                    </button>
                                ))}
                            </span>
                        ) : null}
                    </div>
                </div>
            ) : null}
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeHogQLAttributes>): JSX.Element => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { runHogqlSqlNodeWithMode } = useActions(nodeLogic)

    return (
        <CodeEditorResizeable
            language="sql"
            value={attributes.code}
            onChange={(value) => updateAttributes({ code: value ?? '' })}
            onPressCmdEnter={() => {
                void runHogqlSqlNodeWithMode({ mode: 'auto' })
            }}
            allowManualResize={false}
            minHeight={160}
            embedded
        />
    )
}

export const NotebookNodeHogQL = createPostHogWidgetNode<NotebookNodeHogQLAttributes>({
    nodeType: NotebookNodeType.HogQLSQL,
    titlePlaceholder: 'SQL (HogQL)',
    Component,
    heightEstimate: 120,
    minHeight: 80,
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: {
            default: '',
        },
        returnVariable: {
            default: 'hogql_df',
        },
        hogqlExecution: {
            default: null,
        },
        hogqlExecutionCodeHash: {
            default: null,
        },
        hogqlExecutionSandboxId: {
            default: null,
        },
        showSettings: {
            default: false,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => attrs.code,
})
