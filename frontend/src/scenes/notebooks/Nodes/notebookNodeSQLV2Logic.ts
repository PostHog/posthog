import { actions, afterMount, beforeUnmount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'
import { JSONContent } from 'lib/components/RichContentEditor/types'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { NotebookOperation, notebookOperationsLogic } from '../Notebook/notebookOperationsLogic'
import { collectSqlV2Nodes } from './notebookNodeContent'
import { NotebookNodeSQLV2Result } from './NotebookNodeSQLV2'
import type { notebookNodeSQLV2LogicType } from './notebookNodeSQLV2LogicType'

// Map every SQLV2 sibling's dataframe name -> node id, excluding the running node itself.
// Delegates to collectSqlV2Nodes so duplicate names get the same disambiguated form the
// dependency graph shows (sql_df, sql_df_2, …) — raw attributes would let a later duplicate
// silently shadow the node the user actually referenced. The backend resolves each referenced
// node to its last-run query and inlines it as a CTE — the frontend only supplies the wiring.
export function collectSqlV2Refs(doc: JSONContent | null | undefined, selfNodeId: string): Record<string, string> {
    const refs: Record<string, string> = {}
    for (const node of collectSqlV2Nodes(doc)) {
        if (node.nodeId && node.nodeId !== selfNodeId) {
            refs[node.returnVariable] = node.nodeId
        }
    }
    return refs
}

const POLL_INTERVAL_MS = 1000
const MAX_POLL_ATTEMPTS = 150 // ~2.5 minutes at 1s

export const SQL_V2_DEFAULT_PAGE_SIZE = 50

export type NotebookNodeSQLV2Page = {
    columns: string[]
    types: [string, string][]
    rows: (string | number | null)[][]
    has_more: boolean
}

export interface RunQueryOptions {
    nodeType?: 'hogql' | 'python'
    outputName?: string
}

export interface NotebookNodeSQLV2LogicProps {
    nodeId: string
    notebookShortId: string
    // Current node attributes, so a fresh mount can recover an in-flight/finished run by its runId.
    runId?: string | null
    hasResult?: boolean
    updateAttributes: (attrs: {
        nodeId?: string
        runId?: string | null
        result?: NotebookNodeSQLV2Result | null
    }) => void
}

export const notebookNodeSQLV2Logic = kea<notebookNodeSQLV2LogicType>([
    path((key) => ['scenes', 'notebooks', 'Nodes', 'notebookNodeSQLV2Logic', key]),
    props({} as NotebookNodeSQLV2LogicProps),
    key((props) => props.nodeId),
    connect((props: NotebookNodeSQLV2LogicProps) => ({
        values: [notebookOperationsLogic({ shortId: props.notebookShortId }), ['activeOperation', 'isBusy']],
        actions: [
            notebookOperationsLogic({ shortId: props.notebookShortId }),
            ['startOperation', 'finishOperation', 'finishNodeOperations'],
        ],
    })),
    actions({
        // refs maps each named sibling node's dataframe name to its node id. A hogql node
        // inlines the referenced ones as CTEs (Journey 3); a python node materializes the
        // ones its code reads as pandas frames (Journey 4).
        runQuery: (code: string, refs: Record<string, string> = {}, opts: RunQueryOptions = {}) => ({
            code,
            refs,
            opts,
        }),
        startPolling: (runId: string) => ({ runId }),
        pollResult: (runId: string) => ({ runId }),
        stopPolling: true,
        setIsRunning: (isRunning: boolean) => ({ isRunning }),
        setRunError: (runError: string | null) => ({ runError }),
        setPage: (page: number) => ({ page }),
        setPageSize: (pageSize: number) => ({ pageSize }),
        setPageResult: (pageResult: NotebookNodeSQLV2Page | null) => ({ pageResult }),
        setPageLoading: (pageLoading: boolean) => ({ pageLoading }),
        resetPaging: true,
    }),
    reducers({
        // Tracks the run being in progress; driven by the run's status, not a socket lifecycle.
        isRunning: [
            false,
            {
                runQuery: () => true,
                startPolling: () => true,
                setIsRunning: (_, { isRunning }) => isRunning,
            },
        ],
        runError: [
            null as string | null,
            {
                runQuery: () => null,
                startPolling: () => null,
                setRunError: (_, { runError }) => runError,
            },
        ],
        page: [
            1,
            {
                setPage: (_, { page }) => Math.max(1, page),
                setPageSize: () => 1,
                resetPaging: () => 1,
                runQuery: () => 1,
            },
        ],
        pageSize: [
            SQL_V2_DEFAULT_PAGE_SIZE as number,
            {
                setPageSize: (_, { pageSize }) => pageSize,
                resetPaging: () => SQL_V2_DEFAULT_PAGE_SIZE,
            },
        ],
        // Rows fetched for the current page; null means "show the envelope's first page".
        pageResult: [
            null as NotebookNodeSQLV2Page | null,
            {
                setPageResult: (_, { pageResult }) => pageResult,
                resetPaging: () => null,
                runQuery: () => null,
            },
        ],
        pageLoading: [
            false,
            {
                setPageLoading: (_, { pageLoading }) => pageLoading,
                resetPaging: () => false,
            },
        ],
    }),
    listeners(({ props, actions, cache, values }) => {
        // One operation at a time across the whole notebook (see notebookOperationsLogic);
        // ids are per node + kind so re-registering our own operation stays idempotent.
        const runOperation: NotebookOperation = { id: `${props.nodeId}:run`, nodeId: props.nodeId, kind: 'run' }
        const pageOperation: NotebookOperation = { id: `${props.nodeId}:page`, nodeId: props.nodeId, kind: 'page' }

        const loadCurrentPage = async (): Promise<void> => {
            const { page, pageSize } = values
            const runId = props.runId
            if (!runId) {
                return
            }
            if (page === 1 && pageSize === SQL_V2_DEFAULT_PAGE_SIZE) {
                // The envelope already carries this page — no round trip.
                actions.setPageResult(null)
                return
            }
            // The pagination UI is disabled while the notebook is busy; this guards the
            // programmatic path. A same-node re-page supersedes (stale response discarded below).
            if (values.isBusy && values.activeOperation?.id !== pageOperation.id) {
                lemonToast.info('Another operation is running in this notebook — wait for it to finish.')
                actions.resetPaging()
                return
            }
            actions.startOperation(pageOperation)
            const fetchId = (cache.pageFetchId = (cache.pageFetchId ?? 0) + 1)
            actions.setPageLoading(true)
            try {
                const pageResult = await api.notebooks.sqlV2RunPage(props.notebookShortId, runId, {
                    offset: (page - 1) * pageSize,
                    limit: pageSize,
                })
                if (cache.pageFetchId === fetchId) {
                    actions.setPageResult(pageResult)
                }
            } catch (error: any) {
                if (cache.pageFetchId !== fetchId) {
                    return
                }
                if (error?.status === 409) {
                    lemonToast.info('This result was replaced by a newer run — showing the latest first page.')
                } else {
                    lemonToast.error(error?.detail || error?.message || 'Failed to fetch page')
                }
                // Either way the requested page never arrived — fall back to the envelope's
                // first page rather than showing old rows under a new page number.
                actions.resetPaging()
            } finally {
                // A superseding fetch re-registered the same operation id — leave the release to it.
                if (cache.pageFetchId === fetchId) {
                    actions.setPageLoading(false)
                    actions.finishOperation(pageOperation.id)
                }
            }
        }

        return {
            setPage: loadCurrentPage,
            setPageSize: loadCurrentPage,
            runQuery: async ({ code, refs, opts }) => {
                if (!code.trim()) {
                    actions.setRunError('Nothing to run — type some code first.')
                    actions.setIsRunning(false)
                    return
                }
                // The run button is disabled while the notebook is busy; this guards Cmd+Enter
                // and programmatic dispatch. Re-running our own node supersedes as before.
                if (values.isBusy && values.activeOperation?.nodeId !== props.nodeId) {
                    lemonToast.info('Another operation is running in this notebook — wait for it to finish.')
                    actions.setIsRunning(false)
                    return
                }
                actions.startOperation(runOperation)
                try {
                    const { run_id } = await api.notebooks.sqlV2Run(props.notebookShortId, {
                        node_id: props.nodeId,
                        code,
                        refs,
                        node_type: opts.nodeType,
                        output_name: opts.outputName,
                    })
                    // Mark this as the active run so a still-in-flight poll from a previous run
                    // can't overwrite this result or stop this run's poller once it resolves.
                    cache.activeRunId = run_id
                    // Persisting nodeId pins the cell's identity: markdown-notebook cell ids are
                    // content fingerprints otherwise, so without the pin any later prop change
                    // would orphan this run's node_id and break refs to this cell.
                    props.updateAttributes({ nodeId: props.nodeId, runId: run_id, result: null })
                    actions.startPolling(run_id)
                } catch (error) {
                    actions.setRunError(error instanceof Error ? error.message : 'Failed to run query')
                    actions.setIsRunning(false)
                    actions.finishOperation(runOperation.id)
                }
            },
            startPolling: ({ runId }) => {
                // Idempotent re-register: also covers a remount resuming a persisted in-flight run.
                actions.startOperation(runOperation)
                cache.activeRunId = runId
                cache.pollAttempts = 0
                actions.pollResult(runId)
                // Same key auto-disposes any previous poller; disposables clean up on unmount and pause on hidden tab.
                cache.disposables.add(() => {
                    const intervalId = window.setInterval(() => actions.pollResult(runId), POLL_INTERVAL_MS)
                    return () => clearInterval(intervalId)
                }, 'pollResult')
            },
            pollResult: async ({ runId }) => {
                if (cache.pollInFlight) {
                    return
                }
                cache.pollAttempts = (cache.pollAttempts ?? 0) + 1
                if (cache.pollAttempts > MAX_POLL_ATTEMPTS) {
                    actions.setRunError('Timed out waiting for result')
                    actions.stopPolling()
                    return
                }
                cache.pollInFlight = true
                try {
                    const { status, result, error } = await api.notebooks.sqlV2RunResult(props.notebookShortId, runId)
                    // A newer run started while this poll was in flight — its result and poller
                    // must win, so drop this stale response instead of overwriting/stopping it.
                    if (runId !== cache.activeRunId) {
                        return
                    }
                    if (status === 'done') {
                        props.updateAttributes({
                            result: result
                                ? {
                                      columns: result.columns ?? [],
                                      types: result.types ?? [],
                                      row_count: result.row_count ?? 0,
                                      first_page: result.first_page ?? [],
                                      has_more: result.has_more ?? false,
                                      stdout: result.stdout ?? '',
                                      stderr: result.stderr ?? '',
                                      media: result.media ?? [],
                                  }
                                : null,
                        })
                        // A fresh envelope replaces whatever page the user had drilled into.
                        actions.resetPaging()
                        actions.stopPolling()
                    } else if (status === 'failed') {
                        actions.setRunError(error ?? 'Run failed')
                        actions.stopPolling()
                    }
                    // 'running' → keep polling
                } catch (error) {
                    if (runId !== cache.activeRunId) {
                        return
                    }
                    actions.setRunError(error instanceof Error ? error.message : 'Failed to fetch result')
                    actions.stopPolling()
                } finally {
                    cache.pollInFlight = false
                }
            },
            stopPolling: () => {
                cache.disposables.dispose('pollResult')
                actions.setIsRunning(false)
                actions.finishOperation(runOperation.id)
            },
        }
    }),
    selectors(({ props }) => ({
        // Set while another node's operation is in flight — wire into disabledReason props.
        operationBlockReason: [
            (s) => [s.activeOperation],
            (activeOperation): string | null =>
                activeOperation && activeOperation.nodeId !== props.nodeId
                    ? 'Another operation is running in this notebook'
                    : null,
        ],
    })),
    afterMount(({ props, actions }) => {
        // Recover after a reload/remount: a persisted runId with no result means the run may still be
        // in flight or already finished — poll to catch up rather than lose the result.
        if (props.runId && !props.hasResult) {
            actions.startPolling(props.runId)
        }
    }),
    beforeUnmount(({ props, actions }) => {
        // A deleted or unmounted cell must never leave the notebook wedged as busy.
        actions.finishNodeOperations(props.nodeId)
    }),
])
