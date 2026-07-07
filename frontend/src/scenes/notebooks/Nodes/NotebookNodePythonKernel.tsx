import { useActions, useMountedLogic, useValues } from 'kea'
import { useMemo } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { CodeEditorResizeable } from 'lib/monaco/CodeEditorResizable'

import { NotebookNodeAttributeProperties, NotebookNodeProps } from '../types'
import { NotebookDataframeTable } from './components/NotebookDataframeTable'
import { notebookNodeLogic } from './notebookNodeLogic'
import type { NotebookNodePythonAttributes } from './NotebookNodePython'
import { NotebookNodeSQLV2Result } from './NotebookNodeSQLV2'
import { SQL_V2_DEFAULT_PAGE_SIZE, collectSqlV2Refs, notebookNodeSQLV2Logic } from './notebookNodeSQLV2Logic'
import { NotebookDataframeResult } from './pythonExecution'

// The revamped (v2) Python cell: same ph-python node, but the code runs in the notebook's
// sandbox kernel via the SQLV2 run path, with sibling SQLV2 frames materialized as pandas
// frames. NotebookNodePython renders this when the revamped-py-notebooks flag is on.

const toDataframeResult = (result: NotebookNodeSQLV2Result): NotebookDataframeResult => {
    const columns = result.columns ?? []
    const firstPage = result.first_page ?? []
    return {
        columns,
        rows: firstPage.map((row) => Object.fromEntries(columns.map((column, index) => [column, row[index] ?? null]))),
        rowCount: firstPage.length,
    }
}

export const NotebookNodePythonKernelComponent = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodePythonAttributes>): JSX.Element | null => {
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
        <div data-attr="notebook-node-python" className="flex h-full min-h-0 flex-col">
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

export const NotebookNodePythonKernelSettings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodePythonAttributes>): JSX.Element => {
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
            <div className="flex shrink-0 justify-end border-t p-1" onClick={(event) => event.stopPropagation()}>
                <LemonButton
                    size="xsmall"
                    type="primary"
                    onClick={run}
                    loading={isRunning}
                    disabledReason={operationBlockReason ?? undefined}
                    tooltip="Run Python (⌘⏎)"
                >
                    Run
                </LemonButton>
            </div>
        </div>
    )
}
