import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { projectLogic } from 'scenes/projectLogic'

import { getTasksRunsStreamRetrieveUrl } from 'products/tasks/frontend/generated/api'

import type { taskRunStreamLogicType } from './taskRunStreamLogicType'

export type TaskRunConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

// How long a run may sit in `queued` before we call it stalled. Workers normally pick a run up in
// seconds; minutes of silence means the pipeline isn't running at all.
export const QUEUED_STALL_MS = 2 * 60 * 1000

/**
 * Shapes of the SSE payloads the task-run stream pushes (see the tasks stream view). These are stream
 * messages, not REST serializers, so they're typed here rather than imported from the generated client.
 */
export interface TaskRunStreamState {
    status: string // queued | in_progress | completed | failed | cancelled
    stage: string | null
    output: { pr_url?: string | null } | null
    branch: string | null
    error_message: string | null
    updated_at: string
    completed_at: string | null
}

export interface TaskRunProgressStep {
    step: string
    status: string // in_progress | completed | failed | ...
    label: string
    group: string
    detail: string | null
}

export interface TaskRunStreamLogicProps {
    taskId: string
    runId: string
}

export type TaskRunStreamMessage =
    | { kind: 'state'; state: TaskRunStreamState }
    | { kind: 'step'; step: TaskRunProgressStep }

// Merge a progress step into the list: last-write-wins per (group, step), preserving arrival order.
export function mergeProgressStep(steps: TaskRunProgressStep[], step: TaskRunProgressStep): TaskRunProgressStep[] {
    const idx = steps.findIndex((s) => s.step === step.step && s.group === step.group)
    if (idx === -1) {
        return [...steps, step]
    }
    const next = [...steps]
    next[idx] = step
    return next
}

// Parse one SSE data payload into a typed message, or null if it isn't one we act on (keepalive, a
// non-progress notification, an unknown type). Throws on invalid JSON — the caller surfaces that.
export function parseTaskRunStreamMessage(rawData: string): TaskRunStreamMessage | null {
    const payload = JSON.parse(rawData) as TaskRunStreamState & {
        type?: string
        notification?: { method?: string; params?: TaskRunProgressStep }
    }
    if (payload.type === 'notification') {
        const params = payload.notification?.params
        if (payload.notification?.method !== '_posthog/progress' || !params) {
            return null
        }
        return {
            kind: 'step',
            step: {
                step: params.step,
                status: params.status,
                label: params.label,
                group: params.group,
                detail: params.detail ?? null,
            },
        }
    }
    if (payload.type === 'task_run_state') {
        return {
            kind: 'state',
            state: {
                status: payload.status,
                stage: payload.stage ?? null,
                output: payload.output ?? null,
                branch: payload.branch ?? null,
                error_message: payload.error_message ?? null,
                updated_at: payload.updated_at,
                completed_at: payload.completed_at ?? null,
            },
        }
    }
    return null
}

/**
 * Raw SSE consumer for a single TaskRun (the cloud-run pipeline: provision → clone → wizard → agent →
 * PR). A private source for the Installation layer — `installationProgressLogic` merges this with the
 * wizard session stream and exposes a single `InstallationProgress`. Keyed per run so multiple coexist.
 *
 * Data events (`task_run_state`, `_posthog/progress` notifications) arrive unnamed via `onmessage`;
 * `stream-end` closes the stream; rotation (`end`) and transient drops are handled by EventSource's
 * native reconnect (it replays the `Last-Event-ID` cursor the server stamps on every event).
 */
export const taskRunStreamLogic = kea<taskRunStreamLogicType>([
    props({} as TaskRunStreamLogicProps),
    key((props) => props.runId),
    path((key) => ['scenes', 'onboarding', 'taskRunStreamLogic', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        connect: true,
        disconnect: true,
        taskRunStateUpdated: (state: TaskRunStreamState) => ({ state }),
        progressStepUpdated: (step: TaskRunProgressStep) => ({ step }),
        connectionOpened: true,
        connectionErrored: (error: string) => ({ error }),
        streamCompleted: true,
        runStalled: true,
    }),
    reducers({
        taskRunState: [
            null as TaskRunStreamState | null,
            {
                taskRunStateUpdated: (_, { state }) => state,
            },
        ],
        // Last-write-wins per (group, step), kept in arrival order so the UI renders a stable timeline.
        progressSteps: [
            [] as TaskRunProgressStep[],
            {
                progressStepUpdated: (state, { step }) => mergeProgressStep(state, step),
            },
        ],
        connectionStatus: [
            'idle' as TaskRunConnectionStatus,
            {
                connect: () => 'connecting',
                connectionOpened: () => 'open',
                connectionErrored: () => 'error',
                disconnect: () => 'closed',
                streamCompleted: () => 'closed',
            },
        ],
        isComplete: [
            false,
            {
                streamCompleted: () => true,
            },
        ],
        lastError: [
            null as string | null,
            {
                connect: () => null,
                taskRunStateUpdated: () => null,
                connectionErrored: (_, { error }) => error,
            },
        ],
        // The run has sat in `queued` past the stall window — the backend never picked it up (e.g.
        // no Temporal worker is running). Surfaces render this as a failure instead of an eternal
        // spinner. Cleared as soon as the run reports any non-queued state.
        isStalled: [
            false,
            {
                runStalled: () => true,
                taskRunStateUpdated: (state, { state: runState }) => (runState.status === 'queued' ? state : false),
                connect: () => false,
            },
        ],
    }),
    listeners(({ values, actions, props, cache }) => ({
        // Arm a stall timer while the run reports `queued`; any other status disarms it. The timer
        // rides disposables so unmount (and tab-hide) tears it down with everything else.
        taskRunStateUpdated: ({ state }) => {
            if (state.status !== 'queued') {
                cache.disposables.dispose('queued-stall')
                return
            }
            if (values.isStalled) {
                return
            }
            cache.disposables.add(() => {
                const timer = window.setTimeout(() => actions.runStalled(), QUEUED_STALL_MS)
                return () => window.clearTimeout(timer)
            }, 'queued-stall')
        },
        connect: () => {
            // No run to stream — the Installation layer connects this source even in local mode (where
            // there's no TaskRun), so stay idle rather than opening a stream to a non-existent run.
            if (!props.runId) {
                return
            }
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.connectionErrored('No current project — cannot open task run stream.')
                return
            }

            cache.disposables.add((): (() => void) => {
                const url = getTasksRunsStreamRetrieveUrl(String(projectId), props.taskId, props.runId)
                const eventSource = new EventSource(url, { withCredentials: true })

                eventSource.onopen = actions.connectionOpened
                eventSource.onmessage = (event: MessageEvent<string>): void => {
                    try {
                        const message = parseTaskRunStreamMessage(event.data)
                        if (message?.kind === 'step') {
                            actions.progressStepUpdated(message.step)
                        } else if (message?.kind === 'state') {
                            actions.taskRunStateUpdated(message.state)
                        }
                    } catch (err) {
                        actions.connectionErrored(`Failed to parse SSE payload: ${String(err)}`)
                    }
                }
                // Completion sentinel — close so EventSource doesn't auto-reconnect to a finished run.
                eventSource.addEventListener('stream-end', () => {
                    actions.streamCompleted()
                    eventSource.close()
                })
                eventSource.onerror = (): void => {
                    // CLOSED → browser gave up (won't auto-reconnect); anything else → it's already
                    // retrying (rides the Last-Event-ID cursor), so just surface "reconnecting".
                    if (eventSource.readyState === EventSource.CLOSED) {
                        actions.connectionErrored('EventSource connection closed by server — call connect() to retry')
                    } else {
                        actions.connectionErrored('EventSource transport error — reconnecting')
                    }
                }

                return () => eventSource.close()
            }, 'event-source')
        },
        disconnect: () => {
            cache.disposables.dispose('event-source')
            cache.disposables.dispose('queued-stall')
        },
    })),
])
