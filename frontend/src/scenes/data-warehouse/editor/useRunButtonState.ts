import { useActions, useValues } from 'kea'

import { dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'

import { sqlEditorLogic } from './sqlEditorLogic'

export interface RunButtonHostProps {
    onRunQuery?: () => void
    runQueryLoading?: boolean
    runQueryDisabledReason?: string
    runQueryTooltip?: string
    onCancelQuery?: () => void
    cancelQueryLoading?: boolean
}

export interface RunButtonState {
    /** The button reads Cancel and stops the running query. */
    showCancel: boolean
    /** Whether the query text differs from the query that last ran. */
    hasChangesToRun: boolean
    tooltip: string
    loading: boolean
    /** Whether "Run at cursor" and "Run innermost subquery" are offered next to the button. */
    showRunOptions: boolean
    onClick: () => void
    runAtCursor: () => void
    runInnermostSubquery: () => void
}

/** What the run button shows and does, shared by the Lemon and quill buttons. */
export function useRunButtonState(
    {
        onRunQuery,
        runQueryLoading,
        runQueryTooltip,
        onCancelQuery,
        cancelQueryLoading,
    }: Omit<RunButtonHostProps, 'runQueryDisabledReason'>,
    { allowRunOptions = true }: { allowRunOptions?: boolean } = {}
): RunButtonState {
    const { runQuery, runSubquery } = useActions(sqlEditorLogic)
    const { cancelQuery } = useActions(dataNodeLogic)
    const { responseLoading } = useValues(dataNodeLogic)
    const { isSourceQueryLastRun } = useValues(sqlEditorLogic)

    const isRunning = onRunQuery ? !!runQueryLoading : responseLoading
    // The external-run path shows a cancel affordance only when a canceller is provided.
    const showCancel = isRunning && (!onRunQuery || !!onCancelQuery)

    // No index verdict colors this button. The per-filter report counts filters, and a count does
    // not track what a query costs: one selective filter bounds the read however many others scan,
    // and nothing here yet looks at the time range, which is what really decides how much is read.
    const hasChangesToRun = !!onRunQuery || !isSourceQueryLastRun
    const tooltip = onRunQuery
        ? isRunning && onCancelQuery
            ? 'Stop the running query'
            : (runQueryTooltip ?? 'Run query')
        : isSourceQueryLastRun
          ? 'No changes to run'
          : 'New changes to run'

    return {
        showCancel,
        hasChangesToRun,
        tooltip,
        loading: onRunQuery ? (onCancelQuery ? !!cancelQueryLoading : isRunning) : false,
        showRunOptions: allowRunOptions && !responseLoading && !onRunQuery,
        onClick: () => {
            if (onRunQuery) {
                if (runQueryLoading) {
                    // Guard against double submission: one cancel request at a time.
                    if (onCancelQuery && !cancelQueryLoading) {
                        onCancelQuery()
                    }
                } else {
                    onRunQuery()
                }
            } else if (responseLoading) {
                cancelQuery()
            } else {
                runQuery()
            }
        },
        runAtCursor: () => runQuery(),
        runInnermostSubquery: () => runSubquery(),
    }
}
