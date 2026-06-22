import { BindLogic, useActions, useValues } from 'kea'
import { useEffect } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { sandboxStreamLogic } from '../../sandboxStreamLogic'
import { SandboxThreadView } from './SandboxThreadView'

export interface SandboxRunViewerProps {
    taskId: string
    runId: string
    /** Stable logic key; defaults to `runId` (the run is the unit being viewed). */
    streamKey?: string
    /** Telemetry tag only — omit for conversation-less runs (automation, Slack, signals, PR-triggered). */
    conversationId?: string
    /**
     * Replay the persisted `logs/` snapshot once and never open SSE (default `true`, the safe choice
     * for a static run viewer). Pass `false` for an in-progress run to stream live frames over SSE,
     * falling back to replay automatically once the run goes terminal. Folded into the logic key, so a
     * live and a replay viewer of the same run can never share state.
     */
    replayOnly?: boolean
    className?: string
}

/**
 * Embeddable read-only viewer of a task run's agent thread. Binds a `sandboxStreamLogic` instance
 * (keyed apart from any other stream of the same run) and renders the shared `SandboxThreadView`. With
 * the default `replayOnly`, it replays the persisted `logs/` snapshot once — no SSE. With
 * `replayOnly={false}` it streams an in-progress run live (and replays once terminal). No permissions,
 * no composer. Drop in anywhere with just `(taskId, runId)`.
 */
export function SandboxRunViewer({
    taskId,
    runId,
    streamKey,
    conversationId,
    replayOnly = true,
    className,
}: SandboxRunViewerProps): JSX.Element {
    return (
        <BindLogic logic={sandboxStreamLogic} props={{ streamKey: streamKey ?? runId, conversationId, replayOnly }}>
            <SandboxRunViewerContent taskId={taskId} runId={runId} replayOnly={replayOnly} className={className} />
        </BindLogic>
    )
}

function SandboxRunViewerContent({
    taskId,
    runId,
    replayOnly,
    className,
}: {
    taskId: string
    runId: string
    replayOnly: boolean
    className?: string
}): JSX.Element {
    const { bootstrapLoading, threadItems } = useValues(sandboxStreamLogic)
    const { bootstrapRun, reset } = useActions(sandboxStreamLogic)

    useEffect(() => {
        // Reset first so a reused instance (stable streamKey, changed run) replays/streams the new run
        // cleanly; the bound logic keys read-only instances apart from any live stream of the same run.
        // `replayOnly` is in the deps so a status transition (live → terminal) re-bootstraps the right
        // mode — the bound logic re-keys on it, so `bootstrapRun`/`reset` are fresh references anyway.
        reset()
        bootstrapRun({ taskId, runId })
    }, [taskId, runId, replayOnly, bootstrapRun, reset])

    const showSpinner = bootstrapLoading && threadItems.length === 0

    return (
        <div
            className={cn(
                '@container/thread flex flex-col items-stretch w-full max-w-180 self-center gap-1.5 grow mx-auto',
                className
            )}
        >
            {showSpinner ? (
                <div className="flex justify-center py-8">
                    <Spinner className="text-2xl" />
                </div>
            ) : (
                // An error surfaces as a `handleStreamError` item folded into the thread, so it renders here too.
                <SandboxThreadView />
            )}
        </div>
    )
}
