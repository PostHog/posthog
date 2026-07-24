import { useActions, useMountedLogic, useValues } from 'kea'
import { useEffect, useMemo, useRef } from 'react'

import { IconCornerDownRight } from '@posthog/icons'

import { LemonTabs } from 'lib/lemon-ui/LemonTabs'
import { OutputTab } from 'scenes/data-warehouse/editor/outputPaneLogic'
import { createPostHogWidgetNode } from 'scenes/notebooks/Nodes/NodeWrapper'

import { Query } from '~/queries/Query/Query'
import { DataVisualizationNode, HogQLQueryResponse, NodeKind } from '~/queries/schema/schema-general'
import { ChartDisplayType } from '~/types'

import { NotebookNodeAttributeProperties, NotebookNodeProps, NotebookNodeType } from '../types'
import { NotebookDataframeTable } from './components/NotebookDataframeTable'
import { getCellLabel } from './components/NotebookNodeTitle'
import { NotebookRunDownstreamBanner } from './components/NotebookRunDownstreamBanner'
import { NotebookCodeSQLEditorSettings } from './components/NotebookSQLEditor'
import { NotebookStaleCellBanner } from './components/NotebookStaleCellBanner'
import { notebookNodeLogic } from './notebookNodeLogic'
import { SQL_V2_DEFAULT_PAGE_SIZE, collectSqlV2Refs, notebookNodeSQLV2Logic } from './notebookNodeSQLV2Logic'
import { NotebookDataframeResult } from './pythonExecution'

export type NotebookNodeSQLV2Media = { mime_type: string; data: string }

export type NotebookNodeSQLV2Result = {
    columns: string[]
    types?: [string, string][]
    row_count: number
    first_page: (string | number | null)[][]
    has_more?: boolean
    // Python node output: captured streams and rich media (e.g. matplotlib PNGs).
    stdout?: string
    stderr?: string
    media?: NotebookNodeSQLV2Media[]
}

export type NotebookNodeSQLV2Attributes = {
    code: string
    // Dataframe name other SQLV2 nodes can reference (inlined as a CTE when they join it).
    returnVariable: string
    runId?: string | null
    result?: NotebookNodeSQLV2Result | null
    outputTab?: OutputTab | null
    vizQuery?: DataVisualizationNode | null
}

// Matches the SQL editor output pane's default so charts land at v1-node size.
const VIZ_MIN_HEIGHT = 350
// The default node height only fits a couple of table rows; grow to this once a result lands
// so the output isn't clipped and the user doesn't have to resize by hand to read it.
const RESULT_MIN_HEIGHT = 300

// The dataframe name is referenced as a bare SQL table name and becomes a Python variable
// when a python cell reads the frame, so it must be a plain identifier. Empty is fine —
// the cell is then display-only.
const VALID_RETURN_VARIABLE = /^[A-Za-z_][A-Za-z0-9_]*$/
const returnVariableValidationError = (returnVariable: string): string | null => {
    if (!returnVariable || VALID_RETURN_VARIABLE.test(returnVariable)) {
        return null
    }
    const suggestion = returnVariable.replace(/[^A-Za-z0-9_]/g, '_').replace(/^(?=\d)/, '_')
    const hint = VALID_RETURN_VARIABLE.test(suggestion) ? ` Try ${suggestion}.` : ''
    // Call out only the rule that was actually broken so a name like `people-df` isn't told it
    // "can't start with a number" when the real problem is the hyphen.
    const startsWithDigit = /^\d/.test(returnVariable)
    const hasInvalidChars = /[^A-Za-z0-9_]/.test(returnVariable)
    const reason =
        startsWithDigit && hasInvalidChars
            ? "Use letters, numbers, and underscores, and don't start with a number."
            : startsWithDigit
              ? "The name can't start with a number."
              : 'Use letters, numbers, and underscores.'
    return `${reason}${hint}`
}

const toDataframeResult = (result: NotebookNodeSQLV2Result): NotebookDataframeResult => {
    const columns = result.columns ?? []
    const firstPage = result.first_page ?? []
    return {
        columns,
        rows: firstPage.map((row) => Object.fromEntries(columns.map((column, index) => [column, row[index] ?? null]))),
        // Page over what we actually have; the envelope only carries the first page.
        rowCount: firstPage.length,
    }
}

// Results from before the envelope carried types (or a kernel that omitted them):
// approximate from the first non-null cell so numeric axes still work in charts.
const inferTypes = (result: NotebookNodeSQLV2Result): [string, string][] =>
    (result.columns ?? []).map((column, index) => {
        const sample = (result.first_page ?? []).map((row) => row[index]).find((cell) => cell !== null)
        return [column, typeof sample === 'number' ? 'Float64' : 'String']
    })

const toCachedResults = (result: NotebookNodeSQLV2Result): HogQLQueryResponse => ({
    results: result.first_page ?? [],
    columns: result.columns ?? [],
    types: result.types?.length ? result.types : inferTypes(result),
})

const Component = ({
    attributes,
    updateAttributes,
}: NotebookNodeProps<NotebookNodeSQLV2Attributes>): JSX.Element | null => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic, expanded, sqlV2ReturnVariableUsage } = useValues(nodeLogic)
    const { navigateToNode } = useActions(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: !!attributes.result,
        getContent: () => notebookLogic.values.content ?? null,
    })
    const {
        isRunning,
        runError,
        page,
        pageSize,
        pageResult,
        pageLoading,
        operationBlockReason,
        isStale,
        isChainRunning,
        staleDownstreamCount,
        pendingKernelStart,
    } = useValues(dataLogic)
    const { setPage, setPageSize, runStaleChain } = useActions(dataLogic)

    const usageLabel = (nodeType: NotebookNodeType, nodeIndex: number | undefined, title: string): string =>
        title.trim() || getCellLabel(nodeIndex, nodeType) || 'SQL'

    const result = attributes.result ?? null
    const returnVariableError = returnVariableValidationError(attributes.returnVariable ?? '')
    // Page 1 at the default size comes straight from the envelope; other pages re-query CH.
    const dataframeResult = useMemo(() => {
        if (pageResult) {
            return toDataframeResult({
                columns: pageResult.columns,
                row_count: pageResult.rows.length,
                first_page: pageResult.rows,
            })
        }
        return result ? toDataframeResult(result) : null
    }, [pageResult, result])
    const hasMorePages = pageResult
        ? pageResult.has_more
        : (result?.has_more ?? (result?.first_page ?? []).length >= SQL_V2_DEFAULT_PAGE_SIZE)
    const cachedResults = useMemo(() => (result ? toCachedResults(result) : null), [result])
    const activeTab = attributes.outputTab === OutputTab.Visualization ? OutputTab.Visualization : OutputTab.Results

    // The stored viz config wins, but the source always tracks the node's current code.
    const vizQuery = useMemo(
        (): DataVisualizationNode => ({
            kind: NodeKind.DataVisualizationNode,
            display: ChartDisplayType.ActionsLineGraph,
            ...attributes.vizQuery,
            source: { kind: NodeKind.HogQLQuery, query: attributes.code },
        }),
        [attributes.vizQuery, attributes.code]
    )

    // Grow a still-default (too-short) node the first time a result lands so it's readable
    // without a manual resize. Only grows below the target and only on a fresh result, so a
    // deliberate resize (or a taller reload) is left untouched.
    const hadResultRef = useRef(!!result)
    useEffect(() => {
        const hasResult = !!dataframeResult
        if (hasResult && !hadResultRef.current) {
            const target = activeTab === OutputTab.Visualization ? VIZ_MIN_HEIGHT : RESULT_MIN_HEIGHT
            if (typeof attributes.height !== 'number' || attributes.height < target) {
                updateAttributes({ height: target })
            }
        }
        hadResultRef.current = hasResult
        // oxlint-disable-next-line exhaustive-deps
    }, [dataframeResult])

    if (!expanded) {
        return null
    }

    return (
        <div data-attr="notebook-node-sql-v2" className="flex h-full min-h-0 flex-col">
            <div
                className="flex min-h-0 flex-1 flex-col gap-2"
                onMouseDown={(event) => event.stopPropagation()}
                onDragStart={(event) => event.stopPropagation()}
            >
                {isStale ? (
                    <div className="shrink-0" onClick={(event) => event.stopPropagation()}>
                        <NotebookStaleCellBanner />
                    </div>
                ) : staleDownstreamCount > 0 && !isChainRunning ? (
                    <div className="shrink-0" onClick={(event) => event.stopPropagation()}>
                        <NotebookRunDownstreamBanner
                            count={staleDownstreamCount}
                            onRun={() => runStaleChain(notebookLogic.values.content ?? null, nodeId)}
                            disabledReason={isRunning ? 'This cell is running' : (operationBlockReason ?? undefined)}
                        />
                    </div>
                ) : null}
                {isRunning && pendingKernelStart ? (
                    <div className="shrink-0 px-2 pt-1 text-xs text-muted">Starting compute sandbox…</div>
                ) : null}
                {runError ? (
                    <div className="p-2 text-xs font-mono text-danger whitespace-pre-wrap">{runError}</div>
                ) : dataframeResult && cachedResults ? (
                    <>
                        <div className="shrink-0 px-2 pt-1" onClick={(event) => event.stopPropagation()}>
                            <LemonTabs
                                size="small"
                                activeKey={activeTab}
                                onChange={(tab) => {
                                    // Charts need vertical room; the default node height only fits a few table rows.
                                    const height =
                                        tab === OutputTab.Visualization &&
                                        (typeof attributes.height !== 'number' || attributes.height < VIZ_MIN_HEIGHT)
                                            ? VIZ_MIN_HEIGHT
                                            : attributes.height
                                    updateAttributes({ outputTab: tab, height })
                                }}
                                barClassName="mb-0"
                                tabs={[
                                    { key: OutputTab.Results, label: 'Results' },
                                    { key: OutputTab.Visualization, label: 'Visualization' },
                                ]}
                            />
                        </div>
                        {activeTab === OutputTab.Results ? (
                            <div className="min-h-0 flex-1 overflow-y-auto">
                                <NotebookDataframeTable
                                    result={dataframeResult}
                                    loading={isRunning || pageLoading}
                                    page={page}
                                    pageSize={pageSize}
                                    hasMore={hasMorePages}
                                    // Wide text columns (long strings, JSON blobs) shouldn't make every
                                    // row tall; clamp to one line here and let the user open a cell.
                                    truncateCells
                                    // Serialize page fetches: no new page while one is in flight, a run
                                    // is replacing this result, or another cell's operation is running.
                                    paginationDisabledReason={
                                        pageLoading
                                            ? 'Fetching page…'
                                            : isRunning
                                              ? 'Query is running'
                                              : (operationBlockReason ?? undefined)
                                    }
                                    onNextPage={() => setPage(page + 1)}
                                    onPreviousPage={() => setPage(page - 1)}
                                    onPageSizeChange={setPageSize}
                                />
                            </div>
                        ) : (
                            <div
                                className="px-2 pb-2 flex min-h-0 flex-1 flex-col overflow-hidden"
                                onClick={(event) => event.stopPropagation()}
                            >
                                <Query
                                    // Keyed per run so a fresh envelope re-seeds the cached response.
                                    // The SQLEditor prefix opts into container-governed chart sizing
                                    // (dataVisualizationLogic.presetChartHeight) — without it charts
                                    // render at 60vh, dwarfing the node.
                                    uniqueKey={`SQLEditor-notebook-sqlv2-${nodeId}-${attributes.runId ?? 'initial'}`}
                                    query={vizQuery}
                                    setQuery={(query) => {
                                        // DataVisualization pushes default settings during its render;
                                        // defer the doc write so we don't update Tiptap mid-render.
                                        const vizQuery = query as DataVisualizationNode
                                        setTimeout(() => updateAttributes({ vizQuery }), 0)
                                    }}
                                    cachedResults={cachedResults}
                                    attachTo={notebookLogic}
                                />
                            </div>
                        )}
                    </>
                ) : (
                    <div className="text-xs text-muted font-mono p-2">Run the query to see execution results.</div>
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
                    // A dataframe name other SQL nodes reference by table name (`from sql_df`).
                    // Optional: left empty, the cell is display-only and exports nothing.
                    className="rounded border border-border px-1.5 py-0.5 text-xs font-mono bg-bg-light text-default focus:outline-none focus:ring-1 focus:ring-primary"
                    value={attributes.returnVariable ?? ''}
                    onChange={(event) => updateAttributes({ returnVariable: event.target.value })}
                    placeholder="Dataframe name (optional)"
                    spellCheck={false}
                />
                {returnVariableError ? <span className="text-danger">{returnVariableError}</span> : null}
                {sqlV2ReturnVariableUsage.length > 0 ? (
                    <span className="text-muted">
                        Used in{' '}
                        {sqlV2ReturnVariableUsage.map((usage) => (
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
    )
}

const Settings = ({
    attributes,
    updateAttributes,
}: NotebookNodeAttributeProperties<NotebookNodeSQLV2Attributes>): JSX.Element => {
    const nodeLogic = useMountedLogic(notebookNodeLogic)
    const { nodeId, notebookLogic } = useValues(nodeLogic)
    const notebookShortId = notebookLogic.props.shortId

    const dataLogic = notebookNodeSQLV2Logic({
        nodeId,
        notebookShortId,
        updateAttributes,
        runId: attributes.runId ?? null,
        hasResult: !!attributes.result,
        getContent: () => notebookLogic.values.content ?? null,
    })
    const { isRunning, isInterrupting, operationBlockReason, activeRunLane } = useValues(dataLogic)
    const { runQuery, interruptRun } = useActions(dataLogic)

    return (
        <NotebookCodeSQLEditorSettings
            attributes={attributes}
            updateAttributes={updateAttributes}
            tabIdSuffix="datav2"
            // Refs come from the notebook content, not the tiptap editor: markdown notebooks
            // (the only surface with SQLV2 cells) have no tiptap editor at all.
            onRunQuery={(code) => runQuery(code, collectSqlV2Refs(notebookLogic.values.content, nodeId))}
            runQueryLoading={isRunning}
            runQueryDisabledReason={operationBlockReason ?? undefined}
            runQueryTooltip="Run SQL query"
            // Direct (no-sandbox) runs cannot be cancelled — there is no kernel to signal;
            // they finish on their own bounded schedule. Stop applies to kernel-lane runs only.
            onCancelQuery={activeRunLane === 'kernel' ? interruptRun : undefined}
            cancelQueryLoading={isInterrupting}
        />
    )
}

export const NotebookNodeSQLV2 = createPostHogWidgetNode<NotebookNodeSQLV2Attributes>({
    nodeType: NotebookNodeType.SQLV2,
    titlePlaceholder: 'SQL',
    Component,
    heightEstimate: 120,
    minHeight: 80,
    resizeable: true,
    startExpanded: true,
    attributes: {
        code: {
            default: '',
        },
        // Optional: empty means the cell binds no dataframe (display-only). Existing cells
        // carry their persisted name ('sql_df' was the old default) and keep exporting it.
        returnVariable: {
            default: '',
        },
        runId: {
            default: null,
        },
        result: {
            default: null,
        },
        outputTab: {
            default: OutputTab.Results,
        },
        vizQuery: {
            default: null,
        },
    },
    Settings,
    settingsPlacement: 'inline',
    serializedText: (attrs) => attrs.code,
})
