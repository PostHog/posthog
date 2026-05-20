import { useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { LemonTag } from '@posthog/lemon-ui'

import { wizardSessionStreamLogic } from 'products/wizard/frontend/wizardSessionStreamLogic'

/**
 * Live progress for the AI wizard, shown beneath the run-this-command block.
 *
 * Subscribes to the SSE stream for the (workflow_id, skill_id) the CLI emits
 * during onboarding. The CLI hardcodes `workflow_id = 'onboarding'`; the
 * `skill_id` reflects the framework the wizard detected. Until the CLI exposes
 * a discovery hook, we listen on a single hardcoded skill and render a friendly
 * "waiting for wizard" state when nothing is streaming yet.
 *
 * Keep this UI simple — it's a v1 indicator, not a full progress panel.
 */
const WORKFLOW_ID = 'onboarding'
const SKILL_ID = 'posthog_integration'

export function WizardProgressTracker(): JSX.Element | null {
    const logic = wizardSessionStreamLogic({ workflowId: WORKFLOW_ID, skillId: SKILL_ID })
    const { latestSession, connectionStatus, lastError } = useValues(logic)
    const { connect, disconnect } = useActions(logic)

    useEffect(() => {
        connect()
        return () => disconnect()
    }, [connect, disconnect])

    // Nothing to render until either the stream is open or we have state.
    if (!latestSession && connectionStatus !== 'open') {
        return null
    }

    return (
        <div className="mt-4 p-4 border rounded-lg bg-bg-light">
            <div className="flex items-center justify-between mb-3">
                <h3 className="text-sm font-semibold m-0">Wizard progress</h3>
                <ConnectionBadge status={connectionStatus} />
            </div>

            {latestSession ? (
                <>
                    <div className="flex items-center gap-2 text-xs text-muted mb-2">
                        <span>Run phase:</span>
                        <RunPhaseBadge phase={latestSession.run_phase} />
                    </div>
                    {latestSession.tasks.length === 0 ? (
                        <p className="text-xs text-muted m-0">No tasks reported yet.</p>
                    ) : (
                        <ul className="space-y-1 m-0 pl-0 list-none">
                            {latestSession.tasks.map((task) => (
                                <li key={task.id} className="flex items-center gap-2 text-sm">
                                    <TaskStatusIcon status={task.status} />
                                    <span className={task.status === 'completed' ? 'line-through text-muted' : ''}>
                                        {task.title}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    )}
                    {latestSession.error && (
                        <p className="text-xs text-danger mt-2 m-0">
                            {latestSession.error.type}: {latestSession.error.message}
                        </p>
                    )}
                </>
            ) : (
                <p className="text-xs text-muted m-0">Connected. Waiting for the wizard to push its first update…</p>
            )}

            {lastError && connectionStatus === 'error' && (
                <p className="text-xs text-muted mt-2 m-0">Reconnecting… ({lastError})</p>
            )}
        </div>
    )
}

function ConnectionBadge({ status }: { status: string }): JSX.Element {
    const variant = status === 'open' ? 'success' : status === 'error' ? 'danger' : 'default'
    return (
        <LemonTag type={variant} size="small">
            {status}
        </LemonTag>
    )
}

function RunPhaseBadge({ phase }: { phase: string }): JSX.Element {
    const variant =
        phase === 'completed' ? 'success' : phase === 'error' ? 'danger' : phase === 'running' ? 'primary' : 'default'
    return (
        <LemonTag type={variant} size="small">
            {phase}
        </LemonTag>
    )
}

function TaskStatusIcon({ status }: { status: string }): JSX.Element {
    const symbol =
        status === 'completed'
            ? '✓'
            : status === 'in_progress'
              ? '◔'
              : status === 'failed'
                ? '✗'
                : status === 'cancelled'
                  ? '⊘'
                  : '○'
    const color =
        status === 'completed'
            ? 'text-success'
            : status === 'failed'
              ? 'text-danger'
              : status === 'in_progress'
                ? 'text-primary'
                : 'text-muted'
    return <span className={`font-mono ${color}`}>{symbol}</span>
}
