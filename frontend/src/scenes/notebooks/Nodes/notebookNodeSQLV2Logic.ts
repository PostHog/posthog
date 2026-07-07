import { actions, afterMount, kea, key, listeners, path, props, reducers } from 'kea'

import api from 'lib/api'

import { NotebookNodeSQLV2Result } from './NotebookNodeSQLV2'
import type { notebookNodeSQLV2LogicType } from './notebookNodeSQLV2LogicType'

const POLL_INTERVAL_MS = 1000
const MAX_POLL_ATTEMPTS = 150 // ~2.5 minutes at 1s

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
        runQuery: (code: string) => ({ code }),
        startPolling: (runId: string) => ({ runId }),
        pollResult: (runId: string) => ({ runId }),
        stopPolling: true,
        setIsRunning: (isRunning: boolean) => ({ isRunning }),
        setRunError: (runError: string | null) => ({ runError }),
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
    }),
    listeners(({ props, actions, cache }) => ({
        runQuery: async ({ code }) => {
            if (!code.trim()) {
                actions.setRunError('Query is empty — type some HogQL first.')
                actions.setIsRunning(false)
                return
            }
            try {
                const { run_id } = await api.notebooks.sqlV2Run(props.notebookShortId, {
                    node_id: props.nodeId,
                    code,
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
                              }
                            : null,
                    })
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
    })),
    afterMount(({ props, actions }) => {
        // Recover after a reload/remount: a persisted runId with no result means the run may still be
        // in flight or already finished — poll to catch up rather than lose the result.
        if (props.runId && !props.hasResult) {
            actions.startPolling(props.runId)
        }
    }),
])
