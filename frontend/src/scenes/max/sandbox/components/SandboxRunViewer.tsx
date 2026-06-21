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
    className?: string
}

/**
 * Embeddable, read-only replay of a task run's agent thread. Binds a `replayOnly` `sandboxStreamLogic`
 * instance (keyed separately from any live stream of the same run, so streaming can never bleed in),
 * replays the persisted `logs/` snapshot once, and renders the shared `SandboxThreadView`. No SSE, no
 * permissions, no composer. Drop in anywhere with just `(taskId, runId)`.
 */
export function SandboxRunViewer({
    taskId,
    runId,
    streamKey,
    conversationId,
    className,
}: SandboxRunViewerProps): JSX.Element {
    return (
        <BindLogic
            logic={sandboxStreamLogic}
            props={{ streamKey: streamKey ?? runId, conversationId, replayOnly: true }}
        >
            <SandboxRunViewerContent taskId={taskId} runId={runId} className={className} />
        </BindLogic>
    )
}

function SandboxRunViewerContent({
    taskId,
    runId,
    className,
}: {
    taskId: string
    runId: string
    className?: string
}): JSX.Element {
    const { bootstrapLoading, threadItems } = useValues(sandboxStreamLogic)
    const { bootstrapRun, reset } = useActions(sandboxStreamLogic)

    useEffect(() => {
        // Reset first so a reused instance (stable streamKey, changed run) replays the new snapshot
        // cleanly; the bound logic keys read-only instances apart from any live stream of the same run.
        reset()
        bootstrapRun({ taskId, runId })
    }, [taskId, runId, bootstrapRun, reset])

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
