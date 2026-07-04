import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast/LemonToast'

import { NotebookNodeType } from '../types'
import { NotebookNodeSQLV2Result } from './NotebookNodeSQLV2'
import type { notebookNodeSQLV2LogicType } from './notebookNodeSQLV2LogicType'

// Walk the notebook document for every named SQLV2 node (except this one) and return
// its dataframe name -> node id. The backend resolves each referenced node to its
// last-run query and inlines it as a CTE — the frontend only supplies the wiring.
export function collectSqlV2Refs(doc: unknown, selfNodeId: string): Record<string, string> {
    const refs: Record<string, string> = {}
    const visit = (node: unknown): void => {
        if (!node || typeof node !== 'object') {
            return
        }
        const { type, attrs, content } = node as {
            type?: string
            attrs?: { nodeId?: string; returnVariable?: string }
            content?: unknown[]
        }
        if (type === NotebookNodeType.SQLV2 && attrs && attrs.nodeId && attrs.nodeId !== selfNodeId) {
            const name = attrs.returnVariable?.trim()
            if (name) {
                refs[name] = attrs.nodeId
            }
        }
        if (Array.isArray(content)) {
            content.forEach(visit)
        }
    }
    visit(doc)
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

export interface NotebookNodeSQLV2LogicProps {
    nodeId: string
    notebookShortId: string
    // Current node attributes, so a fresh mount can recover an in-flight/finished run by its runId.
    runId?: string | null
    hasResult?: boolean
    updateAttributes: (attrs: { runId?: string | null; result?: NotebookNodeSQLV2Result | null }) => void
}

export const notebookNodeSQLV2Logic = kea<notebookNodeSQLV2LogicType>([
    path((key) => ['scenes', 'notebooks', 'Nodes', 'notebookNodeSQLV2Logic', key]),
    props({} as NotebookNodeSQLV2LogicProps),
    key((props) => props.nodeId),
    actions({
        // refs maps each named sibling node's dataframe name to its HogQL; the backend
        // inlines the ones this query references as CTEs (Journey 3).
        runQuery: (code: string, refs: Record<string, string> = {}) => ({ code, refs }),
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
                if (cache.pageFetchId === fetchId) {
                    actions.setPageLoading(false)
                }
            }
        }

        return {
            setPage: loadCurrentPage,
            setPageSize: loadCurrentPage,
            runQuery: async ({ code, refs }) => {
                if (!code.trim()) {
                    actions.setRunError('Query is empty — type some HogQL first.')
                    actions.setIsRunning(false)
                    return
                }
                try {
                    const { run_id } = await api.notebooks.sqlV2Run(props.notebookShortId, {
                        node_id: props.nodeId,
                        code,
                        refs,
                    })
                    props.updateAttributes({ runId: run_id, result: null })
                    actions.startPolling(run_id)
                } catch (error) {
                    actions.setRunError(error instanceof Error ? error.message : 'Failed to run query')
                    actions.setIsRunning(false)
                }
            },
            startPolling: ({ runId }) => {
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
                    if (status === 'done') {
                        props.updateAttributes({
                            result: result
                                ? {
                                      columns: result.columns ?? [],
                                      types: result.types ?? [],
                                      row_count: result.row_count ?? 0,
                                      first_page: result.first_page ?? [],
                                      has_more: result.has_more ?? false,
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
                    actions.setRunError(error instanceof Error ? error.message : 'Failed to fetch result')
                    actions.stopPolling()
                } finally {
                    cache.pollInFlight = false
                }
            },
            stopPolling: () => {
                cache.disposables.dispose('pollResult')
                actions.setIsRunning(false)
            },
        }
    }),
    afterMount(({ props, actions }) => {
        // Recover after a reload/remount: a persisted runId with no result means the run may still be
        // in flight or already finished — poll to catch up rather than lose the result.
        if (props.runId && !props.hasResult) {
            actions.startPolling(props.runId)
        }
    }),
])
