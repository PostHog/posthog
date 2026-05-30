import { actions, kea, key, listeners, path, props, reducers, selectors } from 'kea'

import api from 'lib/api'
import { apiHostOrigin } from 'lib/utils/apiHost'

import { TaskRun } from 'products/tasks/frontend/types'

import { resolveToolKey } from './mcpToolRegistry'
import type { sandboxStreamLogicType } from './sandboxStreamLogicType'
import {
    AcpSessionUpdate,
    PermissionRequestRecord,
    RunStatus,
    SseStatus,
    StoredLogEntry,
    ThreadItem,
    ToolInvocation,
    ToolInvocationLocation,
    ToolInvocationStatus,
} from './types/sandboxStreamTypes'

/**
 * Owns the direct browser->cloud-agent SSE connection for the sandbox runtime and folds
 * the ACP wire format into thread-shaped state. Modeled on the proven in-repo consumer
 * products/tasks/frontend/logics/taskDetailSceneLogic.ts startStreaming: a fetch-reader
 * with Last-Event-ID resume, per-event dedup, keepalive skipping, and an AbortController
 * registered via cache.disposables.
 *
 * I2.6 hardening: capped exponential backoff (5 attempts, 2s base, 30s cap) with a REST
 * run-refetch on every drop to detect terminal state BEFORE retrying; serialized-JSON content
 * dedup that reconciles live frames against each other today and is the seam for /log/-replay
 * reconciliation in I2.7 (SSE/Redis ids are not comparable to S3-log ids); error-class mapping
 * (401/403/406/other -> retryable, 404 -> non-retryable new-conversation); terminal task_run_state
 * closes the stream and drives idle/error. All timers/listeners are registered via cache.disposables.
 * The /log/ history fetch + replay itself lands in I2.7 — see ingestHistory. See
 * docs/internal/posthog-ai-migration/02_CORE.md §§4.3,4.4,6.
 */

/** Reconnect schedule — mirrors the cloud-agent desktop client (cloud_implementation.md §5.5). */
export const MAX_SSE_RECONNECT_ATTEMPTS = 5
export const SSE_RECONNECT_BASE_DELAY_MS = 2_000
export const SSE_RECONNECT_MAX_DELAY_MS = 30_000

/** Run statuses past which no further frames will arrive — the run is done. */
const TERMINAL_RUN_STATUSES: ReadonlySet<RunStatus> = new Set<RunStatus>(['completed', 'failed', 'cancelled'])

export function isTerminalRunStatus(status: RunStatus | undefined | null): boolean {
    return status != null && TERMINAL_RUN_STATUSES.has(status)
}

/**
 * Capped exponential backoff: 2s / 4s / 8s / 16s / 30s (the 5th would be 32s, capped to 30s).
 * `attempt` is 1-based — the first retry waits the base delay.
 */
export function computeBackoffDelay(attempt: number): number {
    const exp = SSE_RECONNECT_BASE_DELAY_MS * 2 ** Math.max(0, attempt - 1)
    return Math.min(exp, SSE_RECONNECT_MAX_DELAY_MS)
}

/** A user-visible stream failure mapped from an HTTP status (see §4.4 error table). */
export interface StreamErrorEnvelope {
    errorTitle: string
    /** Retryable surfaces a "Retry" affordance; non-retryable surfaces "create a new conversation". */
    retryable: boolean
    /** Optional detail carried from an ACP `event: error` frame. */
    errorMessage?: string
}

/**
 * Map an HTTP status (from the run refetch or the stream open) to a user-visible error
 * envelope. Same table for non-streamed HTTP failures and ACP `event: error` frames.
 * 404 alone is non-retryable — the backing run is gone, so the user must start fresh.
 */
export function mapStatusToErrorEnvelope(status: number | undefined): StreamErrorEnvelope {
    switch (status) {
        case 401:
            return { errorTitle: 'Cloud authentication expired', retryable: true }
        case 403:
            return { errorTitle: 'Cloud access denied', retryable: true }
        case 404:
            return { errorTitle: 'Conversation backing run not found', retryable: false }
        case 406:
            return { errorTitle: 'Cloud stream unavailable', retryable: true }
        default:
            return { errorTitle: 'Cloud stream failed', retryable: true }
    }
}

/**
 * Stable serialization for content dedup. Today this dedups live frames against each other.
 * It is also the seam I2.7 relies on: SSE ids are Redis stream ids that don't exist in the
 * S3-backed /log/ history, so once /log/-replay lands (I2.7), live frames and replayed history
 * can only be reconciled by serialized-JSON content equality (cloud_implementation.md §9.4).
 * Sorts object keys so two structurally equal frames hash identically regardless of key order.
 */
export function serializeEntryForDedup(entry: StoredLogEntry): string {
    return JSON.stringify(entry, Object.keys(flattenKeys(entry)).sort())
}

/** Collect every nested object key so JSON.stringify's replacer canonicalizes key order. */
function flattenKeys(value: unknown, acc: Record<string, true> = {}): Record<string, true> {
    if (Array.isArray(value)) {
        for (const item of value) {
            flattenKeys(item, acc)
        }
    } else if (value && typeof value === 'object') {
        for (const [k, v] of Object.entries(value)) {
            acc[k] = true
            flattenKeys(v, acc)
        }
    }
    return acc
}

export interface SandboxStreamLogicProps {
    /** Threads its key so per-conversation stream state stays isolated. */
    conversationKey: string
}

export interface SandboxStreamState {
    toolInvocations: Record<string, ToolInvocation>
    threadItems: ThreadItem[]
    runStarted: boolean
    turnComplete: boolean
    currentMode?: string
    currentProgress?: string
    /** Serialized-JSON hashes of ingested frames — dedups live frames today; the /log/-replay vs
     * live-SSE reconciliation it enables lands in I2.7 (see ingestHistory). */
    ingestedEntryHashes: string[]
}

export const EMPTY_STREAM_STATE: SandboxStreamState = {
    toolInvocations: {},
    threadItems: [],
    runStarted: false,
    turnComplete: false,
    ingestedEntryHashes: [],
}

interface ParsedSseEvent {
    data: string
    eventType: string | null
    id: string | null
}

/** Parse one SSE block into its `data` / `event:` / `id:` fields. Ported from taskDetailSceneLogic. */
function parseSseEventBlock(block: string): ParsedSseEvent | null {
    let data = ''
    let eventType: string | null = null
    let id: string | null = null

    for (const line of block.split('\n')) {
        if (!line || line.startsWith(':')) {
            continue
        }
        if (line.startsWith('event:')) {
            eventType = line.slice(6).trim() || null
            continue
        }
        if (line.startsWith('id:')) {
            id = line.slice(3).trim() || null
            continue
        }
        if (line.startsWith('data:')) {
            data = data ? `${data}\n${line.slice(5).trimStart()}` : line.slice(5).trimStart()
        }
    }

    if (!data && !eventType && !id) {
        return null
    }
    return { data, eventType, id }
}

function normalizeStatus(status?: string): ToolInvocationStatus {
    switch (status) {
        case 'in_progress':
            return 'in_progress'
        case 'completed':
            return 'completed'
        case 'failed':
            return 'failed'
        default:
            return 'pending'
    }
}

function getNotification(entry: StoredLogEntry): { method?: string; params?: Record<string, unknown> } | null {
    if (entry.type !== 'notification' || !entry.notification) {
        return null
    }
    return { method: entry.notification.method, params: entry.notification.params }
}

function appendAssistantText(state: SandboxStreamState, id: string, text: string, complete: boolean): ThreadItem[] {
    const items = [...state.threadItems]
    const last = items[items.length - 1]
    if (last && last.kind === 'assistant_message' && !last.complete) {
        items[items.length - 1] = { ...last, text: last.text + text, complete }
        return items
    }
    items.push({ kind: 'assistant_message', id, text, complete })
    return items
}

/**
 * Pure fold of one ACP frame into stream state. Dispatches on `notification.method`
 * (`session/update` discriminated further by `params.update.sessionUpdate`, plus the
 * `_posthog/*` lifecycle methods). Easily unit-testable from StoredLogEntry fixtures.
 * See the dispatch table in docs/internal/posthog-ai-migration/02_CORE.md §6.3.
 */
export function ingestAcpFrame(state: SandboxStreamState, entry: StoredLogEntry, frameId: string): SandboxStreamState {
    const notification = getNotification(entry)
    if (!notification?.method) {
        return state
    }

    // Content dedup against earlier live frames by serialized-JSON equality (and, once I2.7 wires
    // /log/-replay, against replayed history too — SSE/Redis ids aren't comparable to S3-log ids;
    // cloud_implementation.md §9.4).
    const hash = serializeEntryForDedup(entry)
    if (state.ingestedEntryHashes.includes(hash)) {
        return state
    }
    const withHash: SandboxStreamState = { ...state, ingestedEntryHashes: [...state.ingestedEntryHashes, hash] }
    return foldNotification(withHash, notification, frameId)
}

function foldNotification(
    state: SandboxStreamState,
    notification: { method?: string; params?: Record<string, unknown> },
    frameId: string
): SandboxStreamState {
    const { method, params } = notification

    if (method === 'session/update') {
        const update = (params as { update?: AcpSessionUpdate } | undefined)?.update
        if (!update?.sessionUpdate) {
            return state
        }
        return ingestSessionUpdate(state, update, frameId)
    }

    switch (method) {
        case '_posthog/run_started':
            return { ...state, runStarted: true }
        case '_posthog/turn_complete':
            return {
                ...state,
                turnComplete: true,
                threadItems: [...state.threadItems, { kind: 'turn_complete', id: frameId }],
            }
        case '_posthog/progress':
            return { ...state, currentProgress: (params as { message?: string } | undefined)?.message }
        case '_posthog/error': {
            const message = (params as { message?: string } | undefined)?.message ?? 'Unknown error'
            return {
                ...state,
                threadItems: [...state.threadItems, { kind: 'error', id: frameId, message }],
            }
        }
        default:
            // _posthog/usage_update, _posthog/console, _posthog/sdk_session, etc. — ignore.
            return state
    }
}

function ingestSessionUpdate(state: SandboxStreamState, update: AcpSessionUpdate, frameId: string): SandboxStreamState {
    switch (update.sessionUpdate) {
        case 'agent_message_chunk':
            if (update.content?.type === 'text' && update.content.text) {
                return { ...state, threadItems: appendAssistantText(state, frameId, update.content.text, false) }
            }
            return state

        case 'agent_message':
            if (update.content?.type === 'text' && update.content.text) {
                return { ...state, threadItems: appendAssistantText(state, frameId, update.content.text, true) }
            }
            return state

        case 'current_mode_update':
            return { ...state, currentMode: (update as { currentModeId?: string }).currentModeId ?? state.currentMode }

        case 'tool_call':
            return ingestToolCall(state, update, frameId)

        case 'tool_call_update':
            return ingestToolCallUpdate(state, update)

        default:
            return state
    }
}

function ingestToolCall(state: SandboxStreamState, update: AcpSessionUpdate, frameId: string): SandboxStreamState {
    const toolCallId = update.toolCallId || frameId
    const rawServerName = update._meta?.serverName ?? ''
    const rawToolName = update._meta?.claudeCode?.toolName ?? update.title ?? 'unknown'
    const input = update.rawInput ?? {}
    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(rawServerName, rawToolName, input)

    const invocation: ToolInvocation = {
        toolCallId,
        rawServerName,
        rawToolName,
        innerToolName,
        resolvedKey,
        input,
        innerInput,
        status: normalizeStatus(update.status),
        title: update.title,
        kind: update.kind,
        locations: update.locations as ToolInvocationLocation[] | undefined,
        contentBlocks: update.content ? [update.content] : [],
    }

    const alreadyHasItem = state.threadItems.some(
        (item) => item.kind === 'tool_invocation' && item.toolCallId === toolCallId
    )
    return {
        ...state,
        toolInvocations: { ...state.toolInvocations, [toolCallId]: invocation },
        threadItems: alreadyHasItem
            ? state.threadItems
            : [...state.threadItems, { kind: 'tool_invocation', toolCallId }],
    }
}

function ingestToolCallUpdate(state: SandboxStreamState, update: AcpSessionUpdate): SandboxStreamState {
    const toolCallId = update.toolCallId
    if (!toolCallId) {
        return state
    }
    const existing = state.toolInvocations[toolCallId]
    if (!existing) {
        return state
    }

    const merged: ToolInvocation = {
        ...existing,
        status: normalizeStatus(update.status),
        title: update.title ?? existing.title,
        kind: update.kind ?? existing.kind,
        locations: (update.locations as ToolInvocationLocation[] | undefined) ?? existing.locations,
        contentBlocks: update.content ? [...existing.contentBlocks, update.content] : existing.contentBlocks,
        progress: update.rawOutput ?? existing.progress,
        output:
            update._meta?.claudeCode?.toolResponse !== undefined
                ? update._meta.claudeCode.toolResponse
                : update.rawOutput !== undefined
                  ? update.rawOutput
                  : existing.output,
    }
    return { ...state, toolInvocations: { ...state.toolInvocations, [toolCallId]: merged } }
}

export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    path((key) => ['scenes', 'max', 'sandboxStreamLogic', key]),
    props({} as SandboxStreamLogicProps),
    key((props) => props.conversationKey),

    actions({
        /** Open the SSE connection for a cloud-agent run. */
        openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean }) => payload,
        /** Close the SSE connection (conversation change / unmount). */
        closeSse: true,
        setSseStatus: (status: SseStatus) => ({ status }),
        setLastEventId: (lastEventId: string) => ({ lastEventId }),
        setCurrentRunStatus: (status: RunStatus) => ({ status }),
        markEventSeen: (eventId: string) => ({ eventId }),
        setReconnectAttempt: (attempt: number) => ({ attempt }),
        /** Fold one ACP frame into stream state. Dispatched by the live SSE listener (this PR). */
        ingestFrame: (entry: StoredLogEntry, frameId: string) => ({ entry, frameId }),
        /**
         * The /log-replay seam consumed by I2.7 (history-load). Folds a batch of replayed /log/
         * history into stream state and records each frame's dedup hash so the subsequent live SSE
         * doesn't double-count an entry it already replayed. NOT dispatched in this PR — there is no
         * /log/ data source wired yet; I2.7 fetches the history (api.tasks.runs.getLogs) and dispatches
         * this. Kept here because the dedup machinery (serializeEntryForDedup / ingestedEntryHashes)
         * it feeds is exercised by the live path today.
         */
        ingestHistory: (entries: StoredLogEntry[]) => ({ entries }),
        ingestPermissionRequest: (record: PermissionRequestRecord) => ({ record }),
        /** Apply a terminal/lifecycle status (from REST refetch or a task_run_state frame). */
        handleTerminalStatus: (status: RunStatus) => ({ status }),
        /** Surface a mapped stream error envelope to maxThreadLogic / the renderer. */
        handleStreamError: (envelope: StreamErrorEnvelope) => ({ envelope }),
        clearStreamError: true,
        /** Reset all stream state — called when the conversation changes. */
        reset: true,
    }),

    reducers({
        stream: [
            EMPTY_STREAM_STATE,
            {
                ingestFrame: (state, { entry, frameId }) => ingestAcpFrame(state, entry, frameId),
                ingestHistory: (state, { entries }) =>
                    entries.reduce((acc, entry, index) => ingestAcpFrame(acc, entry, `log-${index}`), state),
                reset: () => EMPTY_STREAM_STATE,
            },
        ],
        sseStatus: [
            'idle' as SseStatus,
            {
                openSseForRun: () => 'connecting',
                setSseStatus: (_, { status }) => status,
                closeSse: () => 'closed',
                reset: () => 'idle',
            },
        ],
        lastEventId: [
            undefined as string | undefined,
            {
                setLastEventId: (_, { lastEventId }) => lastEventId,
                reset: () => undefined,
            },
        ],
        seenEventIds: [
            {} as Record<string, true>,
            {
                markEventSeen: (state, { eventId }) => ({ ...state, [eventId]: true }),
                reset: () => ({}),
            },
        ],
        reconnectAttempt: [
            0,
            {
                setReconnectAttempt: (_, { attempt }) => attempt,
                openSseForRun: () => 0,
                // Reset the attempt counter only after a real frame lands, NOT on bare 'open'.
                // An open-then-immediate-EOF run (no terminal frame, REST still in_progress)
                // would otherwise reset on every 'open' and reconnect forever at 2s, never
                // reaching the cap. Counting consecutive open-then-EOF cycles requires a frame
                // to prove the stream actually carried data before we trust it again.
                ingestFrame: () => 0,
                reset: () => 0,
            },
        ],
        currentRunStatus: [
            undefined as RunStatus | undefined,
            {
                setCurrentRunStatus: (_, { status }) => status,
                handleTerminalStatus: (_, { status }) => status,
                reset: () => undefined,
            },
        ],
        streamError: [
            null as StreamErrorEnvelope | null,
            {
                handleStreamError: (_, { envelope }) => envelope,
                clearStreamError: () => null,
                openSseForRun: () => null,
                reset: () => null,
            },
        ],
        pendingPermissionRequest: [
            undefined as PermissionRequestRecord | undefined,
            {
                ingestPermissionRequest: (_, { record }) => record,
                reset: () => undefined,
            },
        ],
    }),

    selectors({
        toolInvocations: [(s) => [s.stream], (stream): Record<string, ToolInvocation> => stream.toolInvocations],
        threadItems: [(s) => [s.stream], (stream): ThreadItem[] => stream.threadItems],
        runStarted: [(s) => [s.stream], (stream): boolean => stream.runStarted],
        turnComplete: [(s) => [s.stream], (stream): boolean => stream.turnComplete],
        currentProgress: [(s) => [s.stream], (stream): string | undefined => stream.currentProgress],
        /** Terminal once the backing run finished (drives idle/read-only in maxThreadLogic). */
        isRunTerminal: [(s) => [s.currentRunStatus], (status): boolean => isTerminalRunStatus(status)],
    }),

    listeners(({ actions, values, cache }) => ({
        openSseForRun: ({ taskId, runId }) => {
            // Tear down any previous stream + pending reconnect first — same key replaces them.
            // Terminal-then-resume swap: a new run's openSseForRun disposes the old run's stream.
            cache.disposables.dispose('sseStream')
            cache.disposables.dispose('sseReconnect')

            cache.disposables.add(() => {
                const abortController = new AbortController()
                // Direct browser->cloud-agent SSE (DECISION 3 "Option B"); session-cookie auth.
                const streamUrl = `${apiHostOrigin()}/api/projects/@current/tasks/${taskId}/runs/${runId}/stream/`

                const consume = async (): Promise<void> => {
                    try {
                        actions.setSseStatus('connecting')
                        const response = await fetch(streamUrl, {
                            signal: abortController.signal,
                            headers: {
                                Accept: 'text/event-stream',
                                ...(values.lastEventId ? { 'Last-Event-ID': values.lastEventId } : {}),
                            },
                        })

                        if (!response.ok || !response.body) {
                            // Non-streamed open failure — map the HTTP status via the §4.4 table.
                            handleOpenFailure(response.status)
                            return
                        }
                        actions.setSseStatus('open')

                        const reader = response.body.getReader()
                        const decoder = new TextDecoder()
                        let buffer = ''
                        let frameIndex = values.stream.threadItems.length

                        while (true) {
                            const { done, value } = await reader.read()
                            if (done) {
                                break
                            }
                            buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, '\n')
                            const blocks = buffer.split('\n\n')
                            buffer = blocks.pop() || ''

                            for (const block of blocks) {
                                const parsed = parseSseEventBlock(block)
                                if (!parsed || parsed.eventType === 'keepalive' || !parsed.data) {
                                    continue
                                }
                                if (parsed.id) {
                                    if (values.seenEventIds[parsed.id]) {
                                        continue
                                    }
                                    actions.markEventSeen(parsed.id)
                                    actions.setLastEventId(parsed.id)
                                }
                                let payload: Record<string, unknown>
                                try {
                                    payload = JSON.parse(parsed.data) as Record<string, unknown>
                                } catch {
                                    continue // Skip invalid JSON frames.
                                }
                                // Control frames carry a `type` discriminator; everything else is a StoredLogEntry.
                                if (parsed.eventType === 'error' || payload.type === 'error') {
                                    const message = typeof payload.error === 'string' ? payload.error : undefined
                                    // Cloud-agent doesn't tag error frames with HTTP status — treat as generic retryable.
                                    actions.handleStreamError({
                                        ...mapStatusToErrorEnvelope(undefined),
                                        errorMessage: message,
                                    })
                                    continue
                                }
                                if (payload.type === 'task_run_state') {
                                    const status = payload.status as RunStatus | undefined
                                    if (status) {
                                        actions.setCurrentRunStatus(status)
                                        // A terminal task_run_state closes the stream and drives idle —
                                        // EOF normally follows, but don't depend on the sentinel arriving.
                                        if (isTerminalRunStatus(status)) {
                                            actions.handleTerminalStatus(status)
                                            actions.setSseStatus('closed')
                                            abortController.abort()
                                            return
                                        }
                                    }
                                    continue
                                }
                                actions.ingestFrame(
                                    payload as unknown as StoredLogEntry,
                                    parsed.id ? `stream-${parsed.id}` : `stream-${frameIndex++}`
                                )
                            }
                        }
                        // EOF: the backend closes on a Redis sentinel with no terminal SSE frame, so
                        // refetch the run via REST to decide terminal-vs-reconnect (§4.3).
                        await onStreamDropped()
                    } catch (e) {
                        if ((e as Error).name === 'AbortError') {
                            return
                        }
                        await onStreamDropped()
                    }
                }

                // On any drop: REST-refetch the run to detect terminal BEFORE retrying.
                const onStreamDropped = async (): Promise<void> => {
                    let run: TaskRun
                    try {
                        run = await api.tasks.runs.get(taskId, runId)
                    } catch (e) {
                        // Refetch itself failed — map its HTTP status (404 non-retryable, else retryable).
                        const status = (e as { status?: number }).status
                        const envelope = mapStatusToErrorEnvelope(status)
                        if (!envelope.retryable) {
                            actions.handleStreamError(envelope)
                            actions.setSseStatus('error')
                            return
                        }
                        scheduleReconnect()
                        return
                    }

                    const runStatus = run.status as RunStatus
                    if (isTerminalRunStatus(runStatus)) {
                        actions.handleTerminalStatus(runStatus)
                        actions.setSseStatus('closed')
                        return
                    }
                    scheduleReconnect()
                }

                // Capped exponential backoff (2/4/8/16/30s, max 5 attempts), then a retryable error.
                const scheduleReconnect = (): void => {
                    const nextAttempt = values.reconnectAttempt + 1
                    if (nextAttempt > MAX_SSE_RECONNECT_ATTEMPTS) {
                        actions.handleStreamError(mapStatusToErrorEnvelope(undefined))
                        actions.setSseStatus('error')
                        return
                    }
                    actions.setReconnectAttempt(nextAttempt)
                    actions.setSseStatus('reconnecting')
                    cache.disposables.add(() => {
                        const timer = window.setTimeout(() => void consume(), computeBackoffDelay(nextAttempt))
                        return () => clearTimeout(timer)
                    }, 'sseReconnect')
                }

                const handleOpenFailure = (status: number): void => {
                    const envelope = mapStatusToErrorEnvelope(status)
                    if (!envelope.retryable) {
                        actions.handleStreamError(envelope)
                        actions.setSseStatus('error')
                        return
                    }
                    scheduleReconnect()
                }

                void consume()
                return () => abortController.abort()
            }, 'sseStream')
        },
        closeSse: () => {
            cache.disposables.dispose('sseStream')
            cache.disposables.dispose('sseReconnect')
        },
        reset: () => {
            cache.disposables.dispose('sseStream')
            cache.disposables.dispose('sseReconnect')
        },
    })),
])
