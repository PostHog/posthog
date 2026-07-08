import { actions, connect, kea, key, listeners, path, props, reducers } from 'kea'

import { logSyncDebug } from 'lib/wizard-sync/wizardSyncDebugLogic'
import { projectLogic } from 'scenes/projectLogic'

import { getTasksRunsStreamRetrieveUrl } from 'products/tasks/frontend/generated/api'
import type { TaskRunDetailDTOApi } from 'products/tasks/frontend/generated/api.schemas'

import { onboardingEventUsageLogic } from '../../onboardingEventUsageLogic'
import { activeCloudRunLogic } from './activeCloudRunLogic'
import type { taskRunStreamLogicType } from './taskRunStreamLogicType'

export type TaskRunConnectionStatus = 'idle' | 'connecting' | 'open' | 'closed' | 'error'

// How long a run may sit in `queued` before we call it stalled. Workers normally pick a run up in
// seconds; minutes of silence means the pipeline isn't running at all.
export const QUEUED_STALL_MS = 2 * 60 * 1000

// Project the REST run snapshot onto the same shape the SSE `task_run_state` events carry, so polling and
// streaming feed `taskRunStateUpdated` identically and the rest of the logic stays mode-agnostic.
export function taskRunDetailToStreamState(dto: TaskRunDetailDTOApi): TaskRunStreamState {
    return {
        status: dto.status,
        stage: dto.stage ?? null,
        output: (dto.output as { pr_url?: string | null } | null) ?? null,
        branch: dto.branch ?? null,
        error_message: dto.error_message ?? null,
        updated_at: dto.updated_at ?? '',
        completed_at: dto.completed_at ?? null,
    }
}

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

export const TERMINAL_TASK_RUN_STATUSES = ['completed', 'failed', 'cancelled'] as const
export type TerminalTaskRunStatus = (typeof TERMINAL_TASK_RUN_STATUSES)[number]

function isTerminalStatus(status: string): status is TerminalTaskRunStatus {
    return (TERMINAL_TASK_RUN_STATUSES as readonly string[]).includes(status)
}

// The agent opens the PR mid-run (while it keeps CI green), so the url arrives via the "pr" progress
// step before the run reaches a terminal output. Prefer the terminal output when present.
export function taskRunPrUrl(state: TaskRunStreamState | null, steps: TaskRunProgressStep[]): string | null {
    // Both sources originate from agent output over the stream — only ever surface http(s) URLs.
    const outputUrl = state?.output?.pr_url
    const prStepUrl = steps.find((s) => s.step === 'pr')?.detail
    return (
        (outputUrl && outputUrl.startsWith('http') ? outputUrl : null) ??
        (prStepUrl && prStepUrl.startsWith('http') ? prStepUrl : null)
    )
}

export interface CloudRunCompletionReport {
    status: TerminalTaskRunStatus
    durationSeconds: number | null
    prOpened: boolean
    prUrl: string | null
}

/**
 * The v2 onboarding funnel's terminal cloud-run event (GROW-89), or null when this state update is
 * not one to report. Only an OBSERVED transition into a terminal status counts: a stream that
 * (re)connects to an already-finished run replays that state, and reporting it would double-count
 * the run — the backend `task_run_completed` / `task_run_failed` events already cover runs that
 * finish while nobody is watching.
 */
export function cloudRunCompletionReport(
    previous: TaskRunStreamState | null,
    state: TaskRunStreamState,
    progressSteps: TaskRunProgressStep[],
    startedAt: string | undefined
): CloudRunCompletionReport | null {
    if (!isTerminalStatus(state.status) || !previous || isTerminalStatus(previous.status)) {
        return null
    }
    // Duration since kickoff (the handle's startedAt) — the stream carries no started_at of its own.
    // The backend's `duration_seconds` (created_at → completed_at) stays the authoritative figure.
    const endedAt = state.completed_at ?? state.updated_at
    const elapsedMs = startedAt && endedAt ? new Date(endedAt).getTime() - new Date(startedAt).getTime() : NaN
    const durationSeconds = Number.isFinite(elapsedMs) ? Math.max(0, Math.round(elapsedMs / 1000)) : null
    const prUrl = taskRunPrUrl(state, progressSteps)
    return { status: state.status, durationSeconds, prOpened: !!prUrl, prUrl }
}

// Terminal outcomes already reported this pageload, keyed by run id. Guards against a re-observed
// transition (e.g. the stream replaying history after a remount) double-counting a run. Mirrors the
// wizard tracker's once-per-session report guards.
const reportedTerminalRuns = new Set<string>()

/**
 * Raw SSE consumer for a single TaskRun (the cloud-run pipeline: provision → clone → wizard → agent →
 * PR). A private source for the Installation layer — `installationProgressLogic` merges this with the
 * wizard session stream and exposes a single `InstallationProgress`. Keyed per run so multiple coexist.
 *
 * Data events (`task_run_state`, `_posthog/progress` notifications) arrive unnamed via `onmessage`;
 * `stream-end` closes the stream; rotation (`end`) and transient drops are handled by EventSource's
 * native reconnect (it replays the `Last-Event-ID` cursor the server stamps on every event).
 *
 * When the `onboarding-wizard-sync-mode` flag resolves to `polling` (GROW-118), the EventSource is
 * replaced by an interval that re-fetches the run's REST snapshot and feeds it through the same
 * `taskRunStateUpdated` action. Polling carries run state only — `_posthog/progress` step
 * notifications are stream-borne, so the step timeline stays empty and surfaces degrade to the
 * coarse run status. The interval comes from the flag payload's `polling_interval_secs`.
 */
export const taskRunStreamLogic = kea<taskRunStreamLogicType>([
    props({} as TaskRunStreamLogicProps),
    key((props) => props.runId),
    path((key) => ['scenes', 'onboarding', 'taskRunStreamLogic', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId'], activeCloudRunLogic, ['activeCloudRun']],
        actions: [onboardingEventUsageLogic, ['reportContextOnboardingCloudRunCompleted']],
    })),
    actions({
        connect: true,
        disconnect: true,
        taskRunStateUpdated: (state: TaskRunStreamState) => ({ state }),
        progressStepUpdated: (step: TaskRunProgressStep) => ({ step }),
        connectionOpened: true,
        connectionErrored: (error: string) => ({ error }),
        // Connect was requested but this run isn't the project's active cloud run — observable so
        // surfaces render idle instead of an eternal "connecting" spinner.
        connectionSkipped: true,
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
                connectionSkipped: () => 'idle',
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
    listeners(({ values, actions, props, cache, selectors }) => ({
        taskRunStateUpdated: ({ state }, _breakpoint, _action, previousState) => {
            // The run's terminal state flows through here no matter which surface is watching (inline
            // install view, sources step, FAB, sidebar button), so this is where the funnel's cloud-run
            // outcome is reported (GROW-89) — the keyed logic dedupes concurrent surfaces to one listener.
            const previous = selectors.taskRunState(previousState)
            // startedAt travels on the persisted run handle; ignore it if the handle is a different run.
            const startedAt = values.activeCloudRun?.runId === props.runId ? values.activeCloudRun.startedAt : undefined
            const report = cloudRunCompletionReport(previous, state, values.progressSteps, startedAt)
            if (report && !reportedTerminalRuns.has(props.runId)) {
                reportedTerminalRuns.add(props.runId)
                actions.reportContextOnboardingCloudRunCompleted({
                    taskId: props.taskId,
                    runId: props.runId,
                    ...report,
                })
            }
            // Arm a stall timer while the run reports `queued`; any other status disarms it. The timer
            // rides disposables so unmount (and tab-hide) tears it down with everything else.
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
                actions.connectionErrored('No current project, cannot open task run stream.')
                return
            }
            // Defense in depth: only sync while this run is the project's active cloud run. If the
            // persisted handle is gone (dismissed, superseded) or belongs to another run, no wizard
            // run is happening for this key — never hold a background stream/poll open for it.
            if (values.activeCloudRun?.runId !== props.runId) {
                logSyncDebug(`run ${props.runId.slice(0, 8)}`, 'connect', 'skipped: not the active cloud run')
                actions.connectionSkipped()
                return
            }

            // SSE only, deliberately NOT governed by the onboarding-wizard-sync-mode flag: that flag
            // controls the WIZARD SESSION transport (whose infra can't take SSE fan-out yet, see
            // wizardSessionStreamLogic), while the per-run TaskRun stream is low-cardinality — one
            // connection per active cloud run — and its REST detail carries no progress steps, so a
            // polled fallback would render an empty pipeline. Cloud runs must work with the session
            // transport in either mode, so the two transports stay independent.
            const debugSource = `run ${props.runId.slice(0, 8)}`

            logSyncDebug(debugSource, 'connect', 'opening EventSource', { mode: 'sse' })
            cache.disposables.add((): (() => void) => {
                const url = getTasksRunsStreamRetrieveUrl(String(projectId), props.taskId, props.runId)
                const eventSource = new EventSource(url, { withCredentials: true })

                eventSource.onopen = (): void => {
                    // Mode rides along here too: the connect event can predate the debug panel's
                    // mount (and get dropped), but open/events always land after it.
                    logSyncDebug(debugSource, 'open', 'SSE connection open', { mode: 'sse' })
                    actions.connectionOpened()
                }
                eventSource.onmessage = (event: MessageEvent<string>): void => {
                    try {
                        const message = parseTaskRunStreamMessage(event.data)
                        if (message?.kind === 'step') {
                            logSyncDebug(
                                debugSource,
                                'event',
                                `step ${message.step.group}/${message.step.step} → ${message.step.status}`
                            )
                            actions.progressStepUpdated(message.step)
                        } else if (message?.kind === 'state') {
                            logSyncDebug(
                                debugSource,
                                'event',
                                `state → ${message.state.status}${message.state.stage ? `/${message.state.stage}` : ''}`
                            )
                            actions.taskRunStateUpdated(message.state)
                        } else {
                            logSyncDebug(debugSource, 'event', 'message ignored (keepalive/unknown type)')
                        }
                    } catch (err) {
                        logSyncDebug(debugSource, 'error', `failed to parse SSE payload: ${String(err)}`)
                        actions.connectionErrored(`Failed to parse SSE payload: ${String(err)}`)
                    }
                }
                // Completion sentinel. Dispose the whole disposable (which closes the EventSource)
                // rather than just closing: a registered-but-closed source would otherwise be
                // reopened by the disposables plugin on tab-visibility resume.
                eventSource.addEventListener('stream-end', () => {
                    logSyncDebug(debugSource, 'complete', 'stream-end received')
                    actions.streamCompleted()
                    cache.disposables.dispose('task-run-sync')
                })
                eventSource.onerror = (): void => {
                    // CLOSED → browser gave up (won't auto-reconnect); anything else → it's already
                    // retrying (rides the Last-Event-ID cursor), so just surface "reconnecting".
                    if (eventSource.readyState === EventSource.CLOSED) {
                        logSyncDebug(debugSource, 'error', 'SSE closed by server')
                        actions.connectionErrored('EventSource connection closed by server — call connect() to retry')
                    } else {
                        logSyncDebug(debugSource, 'error', 'SSE transport error, reconnecting')
                        actions.connectionErrored('EventSource transport error — reconnecting')
                    }
                }

                return () => eventSource.close()
            }, 'task-run-sync')
        },
        disconnect: () => {
            // Tolerant of an empty/absent runId: local mode builds this logic with runId ''.
            logSyncDebug(`run ${String(props.runId ?? '').slice(0, 8)}`, 'disconnect', 'disconnected')
            cache.disposables.dispose('task-run-sync')
            cache.disposables.dispose('queued-stall')
        },
    })),
])
