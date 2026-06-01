import { actions, connect, kea, listeners, path, reducers } from 'kea'

import api from 'lib/api'
import { projectLogic } from 'scenes/projectLogic'

import type { sandboxStreamLogicType } from './sandboxStreamLogicType'
import type {
    PermissionRequestRecord,
    StoredLogEntry,
    ThreadItem,
    ToolInvocation,
    ToolInvocationStatus,
} from './types/sandboxStreamTypes'

export type SandboxSseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'
export type SandboxRunStatus = 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

/** Reconnect/backoff constants — mirrored from PostHog Code (02_CORE.md §§ 4.2, 4.3). */
export const MAX_SSE_RECONNECT_ATTEMPTS = 5
export const SSE_RECONNECT_BASE_DELAY_MS = 2_000
export const SSE_RECONNECT_MAX_DELAY_MS = 30_000

const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled'])

function isTerminalRunStatus(status: string | null | undefined): boolean {
    return status != null && TERMINAL_RUN_STATUSES.has(status)
}

/**
 * Capped exponential backoff: 2s / 4s / 8s / 16s / 30s. `attempt` is 1-based.
 * See 02_CORE.md § 4.3.
 */
export function reconnectDelayMs(attempt: number): number {
    const delay = SSE_RECONNECT_BASE_DELAY_MS * 2 ** (attempt - 1)
    return Math.min(delay, SSE_RECONNECT_MAX_DELAY_MS)
}

export interface StreamErrorEnvelope {
    errorTitle: string
    errorMessage?: string
    retryable: boolean
}

/**
 * HTTP status → user-visible error envelope for refetch/open failures (02_CORE.md § 4.4).
 * Cloud-agent also emits some of these as `event: error` frames; those carry their own
 * envelope and bypass this table.
 */
export function mapHttpStatusToStreamError(status: number | undefined): StreamErrorEnvelope {
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

/** Stable serialized-JSON hash of a StoredLogEntry for content-dedup (02_CORE.md § 4.2). */
function hashLogEntry(entry: StoredLogEntry): string {
    return JSON.stringify(entry)
}

/** Matches `mcp__posthog__exec` (and plugin/regional variants). Ported from Twig posthog-exec-display.ts. */
const POSTHOG_EXEC_TOOL_RE = /^mcp__(?:plugin_)?posthog(?:_[^_]+)*__exec$/

interface ResolvedToolKey {
    resolvedKey: string
    innerToolName?: string
    innerInput?: Record<string, unknown>
}

/**
 * Resolves the registry key for a tool call. The single-exec `posthog` MCP server exposes one
 * outer `exec` tool; the inner tool name is parsed out of `rawInput.command`. Non-exec MCP tools
 * and Claude built-ins look up by their wire name directly. See 03_RICH_UI.md § 2.2.
 */
export function resolveToolKey(serverName: string, toolName: string, input: Record<string, unknown>): ResolvedToolKey {
    const fullName = `mcp__${serverName}__${toolName}`

    if (POSTHOG_EXEC_TOOL_RE.test(fullName) && typeof input.command === 'string') {
        const verbMatch = input.command.match(/^\s*(tools|search|info|schema|call)(?:\s+([\s\S]*))?\s*$/)
        if (!verbMatch) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        const verb = verbMatch[1] as 'tools' | 'search' | 'info' | 'schema' | 'call'
        const rest = (verbMatch[2] ?? '').trim()

        if (verb !== 'call') {
            return { resolvedKey: `__posthog_exec_${verb}__` }
        }

        const callMatch = rest.match(/^(?:--json\s+)?([a-zA-Z0-9_-]+)\s*([\s\S]*)$/)
        if (!callMatch) {
            return { resolvedKey: '__posthog_exec_unknown__' }
        }

        const innerToolName = callMatch[1]
        const jsonBody = (callMatch[2] ?? '').trim()
        let innerInput: Record<string, unknown> = {}
        if (jsonBody) {
            try {
                innerInput = JSON.parse(jsonBody)
            } catch {
                // leave empty
            }
        }
        return { resolvedKey: innerToolName, innerToolName, innerInput }
    }

    return { resolvedKey: toolName }
}

function mapAcpStatus(status: unknown): ToolInvocationStatus {
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

/**
 * Owns the `EventSource` to the products/tasks stream endpoint, parses the ACP wire format, and
 * produces thread-shaped state the renderer consumes. Coexistence sibling to `maxThreadLogic`'s
 * SSE loop — the sandbox path never enters the LangGraph EventSource loop.
 *
 * I1 skeleton: open/close, `data.type === 'notification'` → `ingestAcpFrame`, the § 6.3 dispatch
 * table, terminal status, and stream-error surfacing. I2.6 adds the reconnect/backoff loop
 * (§ 4.3), content-dedup against `logs/` replay (§ 4.2), HTTP-status error mapping (§ 4.4), and the
 * `bootstrapRun` history-replay-then-SSE helper (§ 4.2). See 02_CORE.md § 6.
 */
export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    path(['scenes', 'max', 'sandboxStreamLogic']),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        /**
         * Bootstrap an existing run on conversation open (02_CORE.md § 4.2): replay history from the
         * products/tasks `logs/` endpoint, then open SSE if the run is non-terminal. `justCreatedRun`
         * skips the `logs/` round-trip (fresh-run fast path — nothing historical to assemble).
         */
        bootstrapRun: (payload: { taskId: string; runId: string; justCreatedRun?: boolean }) => payload,
        openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean }) => payload,
        closeSse: true,
        sseConnecting: true,
        sseOpened: true,
        sseReconnecting: (attempt: number) => ({ attempt }),
        /** Internal: an SSE drop initiates the § 4.3 refetch + backoff loop. */
        sseDropped: true,
        /** Frame ingestion — called by the SSE listener and by products/tasks `logs/` replay. */
        ingestAcpFrame: (entry: StoredLogEntry) => ({ entry }),
        /** Internal: records an entry's serialized hash so reconnect replay can dedup it. */
        markEntryIngested: (hash: string) => ({ hash }),
        ingestPermissionRequest: (record: PermissionRequestRecord) => ({ record }),
        handleTerminalStatus: (status: { status: SandboxRunStatus; errorMessage?: string | null }) => status,
        handleStreamError: (envelope: { errorTitle: string; errorMessage?: string; retryable: boolean }) => envelope,
        // Internal state-folding actions emitted by ingestAcpFrame.
        appendAssistantChunk: (id: string, delta: string) => ({ id, delta }),
        finalizeAssistantMessage: (id: string, text: string) => ({ id, text }),
        upsertToolInvocation: (invocation: ToolInvocation) => ({ invocation }),
        updateToolInvocation: (toolCallId: string, patch: Partial<ToolInvocation>) => ({ toolCallId, patch }),
        setCurrentMode: (mode: string) => ({ mode }),
        setCurrentProgress: (progress: string) => ({ progress }),
        markRunStarted: true,
        markTurnComplete: true,
        pushErrorItem: (errorMessage: string) => ({ errorMessage }),
        reset: true,
    }),
    reducers({
        sseStatus: [
            'idle' as SandboxSseStatus,
            {
                sseConnecting: () => 'connecting',
                sseOpened: () => 'open',
                sseReconnecting: () => 'reconnecting',
                closeSse: () => 'closed',
                handleStreamError: () => 'error',
                reset: () => 'idle',
            },
        ],
        reconnectAttempt: [
            0,
            {
                sseReconnecting: (_, { attempt }) => attempt,
                // A successful (re)connection clears the counter; bootstrapping a run starts fresh.
                sseOpened: () => 0,
                bootstrapRun: () => 0,
                reset: () => 0,
            },
        ],
        // Serialized-JSON hashes of entries already ingested (from `logs/` replay or live SSE) so a
        // reconnect with `?start=latest` doesn't double-fold history. See 02_CORE.md § 4.2.
        ingestedEntryHashes: [
            new Set<string>(),
            {
                markEntryIngested: (state, { hash }) => {
                    const next = new Set(state)
                    next.add(hash)
                    return next
                },
                reset: () => new Set<string>(),
            },
        ],
        currentRunStatus: [
            null as SandboxRunStatus | null,
            {
                openSseForRun: () => 'queued',
                handleTerminalStatus: (_, { status }) => status,
                reset: () => null,
            },
        ],
        toolInvocations: [
            new Map<string, ToolInvocation>(),
            {
                upsertToolInvocation: (state, { invocation }) => {
                    const next = new Map(state)
                    next.set(invocation.toolCallId, invocation)
                    return next
                },
                updateToolInvocation: (state, { toolCallId, patch }) => {
                    const existing = state.get(toolCallId)
                    if (!existing) {
                        return state
                    }
                    const next = new Map(state)
                    next.set(toolCallId, { ...existing, ...patch })
                    return next
                },
                reset: () => new Map(),
            },
        ],
        threadItems: [
            [] as ThreadItem[],
            {
                appendAssistantChunk: (state, { id, delta }) => {
                    const idx = state.findIndex((item) => item.type === 'assistant_message' && item.id === id)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text: delta, complete: false }]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text: (next[idx].text ?? '') + delta }
                    return next
                },
                finalizeAssistantMessage: (state, { id, text }) => {
                    const idx = state.findIndex((item) => item.type === 'assistant_message' && item.id === id)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text, complete: true }]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text, complete: true }
                    return next
                },
                upsertToolInvocation: (state, { invocation }) => {
                    if (
                        state.some(
                            (item) => item.type === 'tool_invocation' && item.toolCallId === invocation.toolCallId
                        )
                    ) {
                        return state
                    }
                    return [
                        ...state,
                        { id: invocation.toolCallId, type: 'tool_invocation', toolCallId: invocation.toolCallId },
                    ]
                },
                markTurnComplete: (state) => [...state, { id: `turn-${state.length}`, type: 'turn_separator' }],
                pushErrorItem: (state, { errorMessage }) => [
                    ...state,
                    { id: `error-${state.length}`, type: 'error', errorMessage },
                ],
                reset: () => [],
            },
        ],
        pendingPermissionRequest: [
            null as PermissionRequestRecord | null,
            {
                ingestPermissionRequest: (_, { record }) => record,
                reset: () => null,
            },
        ],
        currentMode: [
            null as string | null,
            {
                setCurrentMode: (_, { mode }) => mode,
                reset: () => null,
            },
        ],
        currentProgress: [
            null as string | null,
            {
                setCurrentProgress: (_, { progress }) => progress,
                markTurnComplete: () => null,
                reset: () => null,
            },
        ],
        runStarted: [
            false,
            {
                markRunStarted: () => true,
                reset: () => false,
            },
        ],
        turnComplete: [
            false,
            {
                markTurnComplete: () => true,
                markRunStarted: () => false,
                reset: () => false,
            },
        ],
    }),
    listeners(({ values, actions, cache }) => ({
        bootstrapRun: async ({ taskId, runId, justCreatedRun }) => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            // Fresh-run fast path (02_CORE.md § 4.2): nothing historical to assemble — go straight to SSE.
            if (justCreatedRun) {
                actions.openSseForRun({ taskId, runId, startLatest: false })
                return
            }

            // Existing run: replay the assembled resume-chain log, then refetch the run to decide on SSE.
            try {
                const entries = await api.tasks.runs.getLogEntries(taskId, runId)
                entries.forEach((entry) => actions.ingestAcpFrame(entry as unknown as StoredLogEntry))
            } catch (error) {
                actions.handleStreamError(mapHttpStatusToStreamError((error as { status?: number })?.status))
                return
            }

            let run: { status?: string }
            try {
                run = await api.tasks.runs.get(taskId, runId)
            } catch (error) {
                actions.handleStreamError(mapHttpStatusToStreamError((error as { status?: number })?.status))
                return
            }

            const status = run.status ?? null
            if (isTerminalRunStatus(status)) {
                // Read-only history — surface the terminal status, do not open SSE.
                actions.handleTerminalStatus({ status: status as SandboxRunStatus })
                return
            }
            // Non-terminal: open SSE from the latest point, deduping against the replayed history.
            actions.openSseForRun({ taskId, runId, startLatest: true })
        },
        openSseForRun: ({ taskId, runId, startLatest }) => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            // Track the active run so the § 4.3 reconnect loop can refetch it on a drop.
            cache.activeRun = { taskId, runId }

            actions.sseConnecting()
            cache.disposables.dispose('reconnect-backoff')

            // Replace any prior connection.
            cache.disposables.dispose('event-source')
            cache.disposables.add((): (() => void) => {
                const start = startLatest ? '?start=latest' : ''
                const url = `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/stream/${start}`
                const eventSource = new EventSource(url, { withCredentials: true })

                eventSource.onopen = (): void => actions.sseOpened()
                eventSource.onmessage = (event: MessageEvent<string>): void => {
                    let data: { type?: string } & Record<string, unknown>
                    try {
                        data = JSON.parse(event.data)
                    } catch {
                        return
                    }
                    switch (data.type) {
                        case 'notification':
                            actions.ingestAcpFrame(data as unknown as StoredLogEntry)
                            break
                        case 'task_run_state':
                            actions.handleTerminalStatus({
                                status: data.status as SandboxRunStatus,
                                errorMessage: (data.errorMessage as string | null) ?? null,
                            })
                            break
                        case 'keepalive':
                            break
                        default:
                            break
                    }
                }
                // `EventSource` fires `error` both for named `event: error` envelopes (carrying `data`,
                // 02_CORE.md § 4.1) and for transient connection drops (no `data`). Surface the former
                // verbatim; treat the latter as a drop and run the § 4.3 refetch + backoff loop.
                eventSource.addEventListener('error', (event: MessageEvent<string>): void => {
                    if (typeof event.data === 'string' && event.data.length > 0) {
                        try {
                            const envelope = JSON.parse(event.data)
                            actions.handleStreamError({
                                errorTitle: envelope.errorTitle ?? 'Cloud stream failed',
                                errorMessage: envelope.errorMessage,
                                retryable: envelope.retryable ?? true,
                            })
                        } catch {
                            actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                        }
                        return
                    }
                    // Connection drop — take over manual reconnection (the native auto-retry would
                    // bypass our refetch + capped-backoff logic).
                    actions.sseDropped()
                })

                return () => eventSource.close()
            }, 'event-source')
        },
        sseDropped: async () => {
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            if (!activeRun) {
                return
            }
            // Stop the native EventSource so its built-in auto-retry doesn't race our loop.
            cache.disposables.dispose('event-source')

            // § 4.3 step 1: refetch the run to detect terminal state.
            let run: { status?: string }
            try {
                run = await api.tasks.runs.get(activeRun.taskId, activeRun.runId)
            } catch (error) {
                actions.handleStreamError(mapHttpStatusToStreamError((error as { status?: number })?.status))
                return
            }

            // § 4.3 step 2: terminal → final terminal-status action + close.
            if (isTerminalRunStatus(run.status ?? null)) {
                actions.handleTerminalStatus({ status: (run.status ?? 'completed') as SandboxRunStatus })
                return
            }

            // § 4.3 step 3: non-terminal → capped exponential backoff, then surface a retryable error.
            const attempt = values.reconnectAttempt + 1
            if (attempt > MAX_SSE_RECONNECT_ATTEMPTS) {
                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                return
            }
            actions.sseReconnecting(attempt)
            cache.disposables.add((): (() => void) => {
                const timer = window.setTimeout(() => {
                    actions.openSseForRun({ taskId: activeRun.taskId, runId: activeRun.runId, startLatest: true })
                }, reconnectDelayMs(attempt))
                return () => clearTimeout(timer)
            }, 'reconnect-backoff')
        },
        handleTerminalStatus: () => {
            // A terminal run has no more frames — close the SSE and stop any pending reconnect.
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        closeSse: () => {
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        reset: () => {
            cache.activeRun = undefined
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        ingestAcpFrame: ({ entry }) => {
            const notification = entry?.notification
            if (!notification) {
                return
            }
            // Content-dedup: a reconnect with `?start=latest` may replay frames already folded in from
            // the `logs/` bootstrap (Redis-stream IDs aren't comparable to S3-log IDs — § 4.2). Match on
            // serialized JSON and drop repeats before they mutate thread state.
            const hash = hashLogEntry(entry)
            if (values.ingestedEntryHashes.has(hash)) {
                return
            }
            actions.markEntryIngested(hash)
            const method = notification.method
            const params = (notification.params ?? {}) as Record<string, any>

            // Custom `_posthog/*` namespace — § 6.3.
            if (method === '_posthog/run_started') {
                actions.markRunStarted()
                return
            }
            if (method === '_posthog/turn_complete') {
                actions.markTurnComplete()
                return
            }
            if (method === '_posthog/progress') {
                actions.setCurrentProgress(String(params.message ?? params.progress ?? ''))
                return
            }
            if (method === '_posthog/error') {
                actions.pushErrorItem(String(params.message ?? notification.error?.message ?? 'Agent error'))
                return
            }
            if (method?.startsWith('_posthog/')) {
                // _posthog/usage_update, _posthog/console, _posthog/sdk_session, _posthog/git_checkpoint, ...
                return
            }

            if (method !== 'session/update') {
                return
            }

            const update = (params.update ?? {}) as Record<string, any>
            const sessionUpdate = update.sessionUpdate as string | undefined

            switch (sessionUpdate) {
                case 'agent_message_chunk': {
                    const id = String(update.messageId ?? 'current')
                    actions.appendAssistantChunk(id, String(update.content?.text ?? update.text ?? ''))
                    break
                }
                case 'agent_message': {
                    const id = String(update.messageId ?? 'current')
                    actions.finalizeAssistantMessage(id, String(update.content?.text ?? update.text ?? ''))
                    break
                }
                case 'tool_call': {
                    const toolCallId = String(update.toolCallId ?? '')
                    if (!toolCallId) {
                        break
                    }
                    const rawServerName = String(update.serverName ?? 'posthog')
                    const rawToolName = String(update.toolName ?? update.title ?? '')
                    const input = (update.rawInput ?? update.input ?? {}) as Record<string, unknown>
                    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(rawServerName, rawToolName, input)
                    actions.upsertToolInvocation({
                        toolCallId,
                        rawServerName,
                        rawToolName,
                        innerToolName,
                        resolvedKey,
                        input,
                        innerInput,
                        status: mapAcpStatus(update.status),
                        title: update.title as string | undefined,
                        kind: update.kind as string | undefined,
                        locations: update.locations as { path: string; line?: number }[] | undefined,
                        contentBlocks: Array.isArray(update.content) ? update.content : [],
                    })
                    break
                }
                case 'tool_call_update': {
                    const toolCallId = String(update.toolCallId ?? '')
                    if (!toolCallId) {
                        break
                    }
                    const existing = values.toolInvocations.get(toolCallId)
                    const mergedContent = existing
                        ? [...existing.contentBlocks, ...(Array.isArray(update.content) ? update.content : [])]
                        : Array.isArray(update.content)
                          ? update.content
                          : []
                    actions.updateToolInvocation(toolCallId, {
                        status: mapAcpStatus(update.status ?? existing?.status),
                        title: (update.title as string | undefined) ?? existing?.title,
                        progress: update.progress ?? existing?.progress,
                        output: update.rawOutput ?? existing?.output,
                        locations:
                            (update.locations as { path: string; line?: number }[] | undefined) ?? existing?.locations,
                        contentBlocks: mergedContent,
                    })
                    break
                }
                case 'current_mode_update': {
                    actions.setCurrentMode(String(update.currentModeId ?? update.mode ?? ''))
                    break
                }
                default:
                    break
            }
        },
    })),
])
