import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCornerDownRight, IconPlayFilled } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { NotebookDataframeTable } from './components/NotebookDataframeTable'
import { notebookNodeLogic } from './notebookNodeLogic'
import type { NotebookNodeSQLV2Result } from './NotebookNodeSQLV2'
import { SQL_V2_DEFAULT_PAGE_SIZE, collectSqlV2Refs, notebookNodeSQLV2Logic } from './notebookNodeSQLV2Logic'
import { NotebookDataframeResult } from './pythonExecution'

// The revamped Python cell: code runs in the notebook's sandbox kernel via the SQLV2 run
// path, with sibling SQLV2 frames materialized as pandas frames. A separate node type from
// the legacy ph-python cell (in-browser kernel) so the two flows never share run wiring.

export type NotebookNodePythonV2Attributes = {
    code: string
    // The dataframe name this cell's result is exposed as to later cells.
    returnVariable: string
    runId?: string | null
    result?: NotebookNodeSQLV2Result | null
}

const toDataframeResult = (result: NotebookNodeSQLV2Result): NotebookDataframeResult => {
    const columns = result.columns ?? []
    const firstPage = result.first_page ?? []
    return {
        columns,
        rows: firstPage.map((row) => Object.fromEntries(columns.map((column, index) => [column, row[index] ?? null]))),
        rowCount: firstPage.length,
    }
}

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePythonV2Attributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic, expanded } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: !!attributes.result,
    })
    const { isRunning, runError, page, pageSize, pageResult, pageLoading, operationBlockReason } = useValues(dataLogic)
    const { setPage, setPageSize } = useActions(dataLogic)

    const result = attributes.result ?? null
    const dataframeResult = useMemo(() => {
        if (pageResult) {
            return toDataframeResult({
                columns: pageResult.columns,
                row_count: pageResult.rows.length,
                first_page: pageResult.rows,
            })
        }
        return result && result.columns?.length ? toDataframeResult(result) : null
    }, [pageResult, result])
    const hasMorePages = pageResult
        ? pageResult.has_more
        : (result?.has_more ?? (result?.first_page ?? []).length >= SQL_V2_DEFAULT_PAGE_SIZE)

    if (!expanded) {
        return null
    }

    const hasStreamOutput = !!(result?.stdout || result?.stderr || result?.media?.length)

    return (
        <div data-attr="notebook-node-python-v2" className="flex h-full min-h-0 flex-col">
            <div
                className="flex min-h-0 flex-1 flex-col gap-2 overflow-y-auto"
                onMouseDown={(event) => event.stopPropagation()}
                onDragStart={(event) => event.stopPropagation()}
            >
                {hasStreamOutput ? (
                    <div className="shrink-0 space-y-2 px-2 pt-1" onClick={(event) => event.stopPropagation()}>
                        {result?.stdout ? (
                            <pre className="text-xs font-mono whitespace-pre-wrap select-text m-0">{result.stdout}</pre>
                        ) : null}
                        {result?.stderr ? (
                            <pre className="text-xs font-mono whitespace-pre-wrap text-danger select-text m-0">
                                {result.stderr}
                            </pre>
                        ) : null}
                        {result?.media?.map((item, index) => (
                            <img
                                key={index}
                                src={`data:${item.mime_type};base64,${item.data}`}
                                alt="Python output"
                                className="max-w-full rounded border border-border bg-white"
                            />
                        ))}
                    </div>
                ) : null}
                {runError ? (
                    <div className="p-2 text-xs font-mono text-danger whitespace-pre-wrap">{runError}</div>
                ) : dataframeResult ? (
                    <div className="min-h-0 flex-1 overflow-y-auto">
                        <NotebookDataframeTable
                            result={dataframeResult}
                            loading={isRunning || pageLoading}
                            page={page}
                            pageSize={pageSize}
                            hasMore={hasMorePages}
                            paginationDisabledReason={
                                pageLoading
                                    ? 'Fetching page…'
                                    : isRunning
                                      ? 'Cell is running'
                                      : (operationBlockReason ?? undefined)
                            }
                            onNextPage={() => setPage(page + 1)}
                            onPreviousPage={() => setPage(page - 1)}
                            onPageSizeChange={setPageSize}
                        />
                    </div>
                ) : hasStreamOutput ? null : (
                    <div className="text-xs text-muted font-mono p-2">Run the cell to see execution results.</div>
                )}
                {attributes.runId ? (
                    <div className="shrink-0 px-2 pb-2 text-[10px] uppercase tracking-wide text-muted select-text">
                        run_id: {attributes.runId}
                    </div>
                ) : null}
            </div>
            <div
                className="flex shrink-0 items-center gap-2 text-xs text-muted border-t p-2"
                onClick={(event) => event.stopPropagation()}
                onMouseDown={(event) => event.stopPropagation()}
            >
                <span className="font-mono mt-0.5">
                    <IconCornerDownRight />
                </span>
                <input
                    type="text"
                    // The dataframe name this cell's result is exposed as to later cells.
                    className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default focus:outline-none focus:ring-1 focus:ring-primary"
                    value={attributes.returnVariable ?? ''}
                    onChange={(event) => updateAttributes({ returnVariable: event.target.value })}
                    spellCheck={false}
                />
            </div>
        </div>
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePythonV2Attributes>): JSX.Element => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: !!attributes.result,
    })
    const { isRunning, operationBlockReason } = useValues(dataLogic)
    const { runQuery } = useActions(dataLogic)

    const run = (): void => {
        // The refs map sibling SQLV2 frames; the backend materializes only the ones the code reads.
        runQuery(attributes.code ?? '', collectSqlV2Refs(notebookLogic.values.content, nodeId), {
            nodeType: 'python',
            outputName: attributes.returnVariable,
        })
    }

    return (
        <div className="flex h-full min-h-0 flex-col">
            {/* Mirrors the embedded SQL editor's toolbar (QueryWindow) so code cells look alike. */}
            <div
                className="flex w-full shrink-0 flex-row items-center gap-2 border-t border-b bg-white py-1 pl-2 pr-2 dark:bg-black"
                onClick={(event) => event.stopPropagation()}
            >
                <LemonButton
                    data-attr="notebook-python-v2-run-button"
                    size="small"
                    type="primary"
                    icon={<IconPlayFilled color="var(--success)" />}
                    onClick={() => {
                        if (!isRunning) {
                            run()
                        }
                    }}
                    loading={isRunning}
                    disabledReason={operationBlockReason ?? undefined}
                    tooltip="Run Python (⌘⏎)"
                >
                    Run
                </LemonButton>
            </div>
            <div className="min-h-0 flex-1">
                <CodeEditorResizeable
                    language="python"
                    value={typeof attributes.code === 'string' ? attributes.code : ''}
                    onChange={(value) => updateAttributes({ code: value ?? '' })}
                    onPressCmdEnter={run}
                    allowManualResize={false}
                    minHeight={160}
                    embedded
                />
            </div>
        </div>
    )
}

export const NotebookNodePythonV2 = createPostHogWidgetNode<NotebookNodePythonV2Attributes>({
    nodeType: NotebookNodeType.PythonV2,
    titlePlaceholder: 'Python',
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
            default: 'df',
        },
        runId: {
            default: null,
        },
        result: {
            default: null,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => attrs.code,
})
