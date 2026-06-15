import { actions, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import type { sandboxStreamLogicType } from './sandboxStreamLogicType'
import { defaultPermissionDecision, findAllowOptionId } from './sandboxToolPolicy'
import type {
    PermissionRequestRecord,
    ThreadItem,
    ThreadItemType,
    ToolInvocation,
    ToolInvocationStatus,
} from './types/sandboxStreamTypes'
import {
    type PermissionOption,
    type PermissionRequestFrame,
    type PosthogErrorParams,
    type PosthogPermissionRequestParams,
    type PosthogProgressParams,
    type SseErrorFrameData,
    type StoredLogEntry,
    isKnownSessionUpdate,
    isNotificationFrame,
    isPermissionRequestFrame,
    isPosthogNotification,
    isSessionUpdateNotification,
    isTaskRunStateFrame,
} from './types/sandboxWireTypes'

export type SandboxSseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'
export type SandboxRunStatus = 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface SandboxStreamLogicProps {
    conversationId: string
}

/** Reconnect/backoff constants for the SSE drop-recovery loop. */
export const MAX_SSE_RECONNECT_ATTEMPTS = 5
export const SSE_RECONNECT_BASE_DELAY_MS = 2_000
export const SSE_RECONNECT_MAX_DELAY_MS = 30_000

const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled'])

function isTerminalRunStatus(status: string | null | undefined): boolean {
    return status != null && TERMINAL_RUN_STATUSES.has(status)
}

/** Capped exponential backoff: 2s / 4s / 8s / 16s / 30s. `attempt` is 1-based. */
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
 * HTTP status → user-visible error envelope for refetch/open failures. Cloud-agent also emits
 * some of these as `event: error` frames; those carry their own envelope and bypass this table.
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

/** Stable serialized-JSON hash of a StoredLogEntry for content-dedup. */
function hashLogEntry(entry: StoredLogEntry): string {
    return JSON.stringify(entry)
}

/** Refetch the run's status; on failure return the mapped error envelope instead. */
async function fetchRunStatus(
    taskId: string,
    runId: string
): Promise<{ status: string | null } | { error: StreamErrorEnvelope }> {
    try {
        const run: { status?: string } = await api.tasks.runs.get(taskId, runId)
        return { status: run.status ?? null }
    } catch (error) {
        return { error: mapHttpStatusToStreamError((error as { status?: number })?.status) }
    }
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
 * and Claude built-ins look up by their wire name directly.
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

/**
 * Finds the last buffer of `type` for a wire message id, also matching the derived `${id}@<n>` ids
 * minted when the wire omits `messageId` and every chunk shares the fallback id. Shared by the
 * assistant-message and agent-thought streams, which both buffer incremental chunks this way.
 */
function findLastBufferIndex(state: ThreadItem[], id: string, type: ThreadItemType, incompleteOnly: boolean): number {
    for (let i = state.length - 1; i >= 0; i--) {
        const item = state[i]
        if (
            item.type === type &&
            (item.id === id || item.id.startsWith(`${id}@`)) &&
            (!incompleteOnly || !item.complete)
        ) {
            return i
        }
    }
    return -1
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

function parsePermissionOption(raw: unknown): PermissionOption | null {
    if (typeof raw !== 'object' || raw === null) {
        return null
    }
    const r = raw as Record<string, unknown>
    const optionId = r.optionId
    const kind = String(r.kind ?? '')
    // Require only the two fields the card acts on: the `optionId` forwarded on the reply and a
    // non-empty `kind` to classify. The kind vocabulary tracks the agent adapter (`reject` became
    // `reject_once`, etc.), so accept any non-empty kind and let the prefix-based mapper resolve the
    // affordance — an exact-match allowlist silently dropped unknown kinds and blanked the prompt
    // whenever none survived.
    if (typeof optionId !== 'string' || !kind) {
        return null
    }
    const meta = r._meta
    const customInput =
        typeof meta === 'object' && meta !== null && (meta as Record<string, unknown>).customInput === true
    return {
        optionId,
        name: String(r.name ?? ''),
        kind,
        customInput,
    }
}

/**
 * Parses a permission request into a `PermissionRequestRecord` — either the live
 * `data.type === 'permission_request'` SSE envelope or the `_posthog/permission_request`
 * notification params the agent-server persists to the run log (both carry the same fields).
 * The toolCall payload mirrors the ACP `tool_call` shape; reusing `resolveToolKey` keys the
 * request onto the same `toolCallId` as the rendered tool card. Returns null when the frame
 * is malformed or carries no usable options. The wire payload is typed, not validated, so
 * every field read keeps its runtime check.
 */
export function parsePermissionRequestFrame(
    frame: PermissionRequestFrame | PosthogPermissionRequestParams
): PermissionRequestRecord | null {
    const requestId = frame.requestId
    if (typeof requestId !== 'string') {
        return null
    }
    const toolCall = (frame.toolCall ?? {}) as Record<string, unknown>
    const toolCallId = String(toolCall.toolCallId ?? frame.toolCallId ?? '')
    if (!toolCallId) {
        return null
    }
    const options = Array.isArray(frame.options)
        ? frame.options.map(parsePermissionOption).filter((o): o is PermissionOption => o !== null)
        : []
    if (options.length === 0) {
        return null
    }

    const rawServerName = String(toolCall.serverName ?? 'posthog')
    const rawToolName = String(toolCall.toolName ?? toolCall.title ?? '')
    const input = (toolCall.rawInput ?? toolCall.input ?? {}) as Record<string, unknown>
    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(rawServerName, rawToolName, input)

    // Canonical ACP tool name (e.g. `mcp__posthog__exec`, or a built-in like `Bash`). The wire puts
    // it on `_meta.claudeCode.toolName`; the bare fields are the fallback. The default permission
    // policy classifies off this — `mcp__`-prefixed vs built-in, plus the exec sub-tool.
    const meta = (toolCall._meta ?? {}) as Record<string, unknown>
    const claudeCode = (meta.claudeCode ?? {}) as Record<string, unknown>
    const toolName = String(claudeCode.toolName ?? toolCall.toolName ?? rawToolName)

    return {
        requestId,
        toolCallId,
        toolName,
        options,
        title: toolCall.title as string | undefined,
        description: toolCall.description as string | undefined,
        rawToolCall: {
            toolCallId,
            rawServerName,
            rawToolName,
            innerToolName,
            resolvedKey,
            input,
            innerInput,
            status: mapAcpStatus(toolCall.status),
            title: toolCall.title as string | undefined,
            kind: toolCall.kind as string | undefined,
            locations: toolCall.locations as { path: string; line?: number }[] | undefined,
            contentBlocks: Array.isArray(toolCall.content) ? toolCall.content : [],
        },
    }
}

/**
 * Owns the `EventSource` to the products/tasks stream endpoint, parses the ACP wire format, and
 * produces thread-shaped state the renderer consumes. Coexistence sibling to `maxThreadLogic`'s
 * SSE loop — the sandbox path never enters the LangGraph EventSource loop.
 *
 * Covers open/close, `data.type === 'notification'` → `ingestAcpFrame` dispatch, terminal status,
 * and stream-error capture, plus the reconnect/backoff loop on SSE drops, content-dedup against
 * the `logs/` replay, HTTP-status error mapping, and the `bootstrapRun` history-replay-then-SSE
 * helper.
 *
 * Keyed by conversation id so concurrent conversations keep independent stream state and
 * EventSource connections.
 */
export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    props({} as SandboxStreamLogicProps),
    key((props) => props.conversationId),
    path((key) => ['scenes', 'max', 'sandboxStreamLogic', key]),
    connect(() => ({
        values: [projectLogic, ['currentProjectId']],
    })),
    actions({
        /**
         * Bootstrap an existing run on conversation open: replay history from the products/tasks
         * `logs/` endpoint, then open SSE if the run is non-terminal. `justCreatedRun` skips the
         * `logs/` round-trip (fresh-run fast path — nothing historical to assemble).
         */
        bootstrapRun: (payload: { taskId: string; runId: string; justCreatedRun?: boolean; traceId?: string }) =>
            payload,
        openSseForRun: (payload: { taskId: string; runId: string; startLatest?: boolean; traceId?: string }) => payload,
        closeSse: true,
        sseConnecting: true,
        sseOpened: true,
        sseReconnecting: (attempt: number) => ({ attempt }),
        /** Internal: an SSE drop initiates the refetch + backoff loop. */
        sseDropped: true,
        /** Frame ingestion — called by the SSE listener and by products/tasks `logs/` replay. */
        ingestAcpFrame: (entry: StoredLogEntry) => ({ entry }),
        /** Internal: records an entry's serialized hash so reconnect replay can dedup it. */
        markEntryIngested: (hash: string) => ({ hash }),
        /**
         * Surface a permission request. `replayedFromHistory` marks requests re-derived from the
         * `logs/` bootstrap — they restore card state but don't re-fire telemetry (the event
         * already fired when the request was live).
         */
        ingestPermissionRequest: (record: PermissionRequestRecord, replayedFromHistory: boolean = false) => ({
            record,
            replayedFromHistory,
        }),
        /**
         * Entry point for every parsed permission request. Applies the default tool policy
         * (`sandboxToolPolicy`): auto-approve built-in tools + non-destructive PostHog exec, prompt
         * for update/delete exec (and other MCP). Replayed-from-history requests are never
         * auto-approved — they're a read-only restore and the run may already be terminal.
         */
        routePermissionRequest: (record: PermissionRequestRecord, replayedFromHistory: boolean = false) => ({
            record,
            replayedFromHistory,
        }),
        /** Silently POST `allow` for a request the default policy auto-approves (no card shown). */
        autoApprovePermissionRequest: (record: PermissionRequestRecord, optionId: string) => ({ record, optionId }),
        /** Pin a requestId as seen without surfacing a card, so a reconnect replay can't re-process it. */
        markPermissionRequestSeen: (requestId: string) => ({ requestId }),
        /**
         * The request was answered — by this client (successful POST), another tab/client, or a
         * `_posthog/permission_resolved` log entry. Clears the matching card and pins the id so
         * reconnect/bootstrap replays cannot re-surface it.
         */
        markPermissionRequestResolved: (requestId: string) => ({ requestId }),
        /**
         * User picked an option on the approval card. POSTs the reply to the sandbox `permission/`
         * endpoint (which routes to the products/tasks `permission_response` command); the pending
         * request clears only once the POST succeeds, so a failure keeps the card for retry.
         * `customInput` carries `reject_with_feedback` text.
         */
        respondToPermission: (payload: {
            conversationId: string
            requestId: string
            optionId: string
            customInput?: string
        }) => payload,
        clearPermissionRequest: true,
        /**
         * Internal: the reply POST failed. Resets the in-flight flag (so the surviving card's
         * buttons re-enable for retry) without coupling that reset to unrelated stream errors.
         */
        permissionResponseFailed: true,
        handleTerminalStatus: (status: {
            status: SandboxRunStatus
            errorMessage?: string | null
            replayedFromHistory?: boolean
        }) => status,
        handleStreamError: (envelope: { errorTitle: string; errorMessage?: string; retryable: boolean }) => envelope,
        // Internal state-folding actions emitted by ingestAcpFrame.
        appendAssistantChunk: (id: string, delta: string) => ({ id, delta }),
        finalizeAssistantMessage: (id: string, text: string) => ({ id, text }),
        /** Appends a streamed reasoning chunk to the trailing thought buffer (or opens a new one). */
        appendThoughtChunk: (id: string, delta: string) => ({ id, delta }),
        upsertToolInvocation: (invocation: ToolInvocation) => ({ invocation }),
        updateToolInvocation: (toolCallId: string, patch: Partial<ToolInvocation>) => ({ toolCallId, patch }),
        setCurrentMode: (mode: string) => ({ mode }),
        setCurrentProgress: (progress: string) => ({ progress }),
        markRunStarted: true,
        markTurnComplete: true,
        /** Echoes the user's own message into the thread — the sandbox wire never replays it. */
        pushHumanMessage: (content: string) => ({ content }),
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
        // reconnect with `?start=latest` doesn't double-fold history.
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
                // A reconnect reopens the same in-flight run — keep its known status rather than
                // flickering back to queued; only a fresh open (no/terminal status) resets.
                openSseForRun: (state) => (state && !isTerminalRunStatus(state) ? state : 'queued'),
                handleTerminalStatus: (_, { status }) => status,
                reset: () => null,
            },
        ],
        // Trace correlation for the telemetry inventory. The SSE bypasses Django, so the frontend
        // supplies the trace_id it minted for POST /sandbox/ when it opened the run; conversation_id
        // is this keyed logic's own props.conversationId. Undefined for history-loaded runs — a
        // reload can't recover the trace_id the original run was sent under.
        traceId: [
            null as string | null,
            {
                bootstrapRun: (state, { traceId }) => traceId ?? state,
                openSseForRun: (state, { traceId }) => traceId ?? state,
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
                    const idx = findLastBufferIndex(state, id, 'assistant_message', false)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text: delta, complete: false }]
                    }
                    // Continue the matched buffer only if it is still the thread tail. A finalized
                    // buffer, or one with another item appended after it (a tool call, separator,
                    // error), must not absorb the chunk — text resuming after a tool call is its own
                    // message and has to render in chronological order. The wire often omits
                    // messageId, so a fresh bubble gets a uniquified id.
                    if (state[idx].complete || idx !== state.length - 1) {
                        return [
                            ...state,
                            { id: `${id}@${state.length}`, type: 'assistant_message', text: delta, complete: false },
                        ]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text: (next[idx].text ?? '') + delta }
                    return next
                },
                finalizeAssistantMessage: (state, { id, text }) => {
                    const idx = findLastBufferIndex(state, id, 'assistant_message', true)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_message', text, complete: true }]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text, complete: true }
                    return next
                },
                appendThoughtChunk: (state, { id, delta }) => {
                    const idx = findLastBufferIndex(state, id, 'assistant_thought', false)
                    if (idx === -1) {
                        return [...state, { id, type: 'assistant_thought', text: delta, complete: false }]
                    }
                    // Same tail rule as assistant chunks: keep buffering only while the thought is
                    // still the thread tail. Once a message or tool call lands after it, a fresh
                    // chunk opens a new bubble so reasoning renders in chronological order. The wire
                    // omits messageId, so every thought shares the fallback id — uniquify the bubble.
                    if (state[idx].complete || idx !== state.length - 1) {
                        return [
                            ...state,
                            { id: `${id}@${state.length}`, type: 'assistant_thought', text: delta, complete: false },
                        ]
                    }
                    const next = [...state]
                    next[idx] = { ...next[idx], text: (next[idx].text ?? '') + delta }
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
                pushHumanMessage: (state, { content }) => [
                    ...state,
                    { id: `human-${state.length}`, type: 'human_message', text: content, complete: true },
                ],
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
                // Cleared on resolution (successful POST or a permission_resolved entry), NOT on
                // respondToPermission dispatch — a failed POST keeps the card so the user can retry.
                markPermissionRequestResolved: (state, { requestId }) =>
                    state?.requestId === requestId ? null : state,
                clearPermissionRequest: () => null,
                // A terminal run can't accept approvals — drop a card re-derived from its history.
                handleTerminalStatus: (state, { status }) => (isTerminalRunStatus(status) ? null : state),
                reset: () => null,
            },
        ],
        // requestIds ever surfaced, so a reconnect's full replay can't double-fire telemetry or
        // re-ingest a request this client already knows about.
        seenPermissionRequestIds: [
            new Set<string>(),
            {
                ingestPermissionRequest: (state, { record }) => {
                    const next = new Set(state)
                    next.add(record.requestId)
                    return next
                },
                markPermissionRequestSeen: (state, { requestId }) => {
                    const next = new Set(state)
                    next.add(requestId)
                    return next
                },
                reset: () => new Set<string>(),
            },
        ],
        // requestIds answered (locally or observed via permission_resolved) — replayed requests
        // with these ids must never re-surface as pending.
        resolvedPermissionRequestIds: [
            new Set<string>(),
            {
                markPermissionRequestResolved: (state, { requestId }) => {
                    const next = new Set(state)
                    next.add(requestId)
                    return next
                },
                reset: () => new Set<string>(),
            },
        ],
        // In-flight state for the approval reply POST — drives the input card's loading/disabled
        // props. Cleared on resolution (success) and on the POST's own failure (the card stays
        // pending, so the buttons must re-enable for retry).
        respondingToPermission: [
            false,
            {
                respondToPermission: () => true,
                markPermissionRequestResolved: () => false,
                clearPermissionRequest: () => false,
                permissionResponseFailed: () => false,
                reset: () => false,
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
    selectors({
        /**
         * Whether the agent is actively working a turn — drives the thread's thinking indicator.
         * Off once the turn completes, the run reaches a terminal status (a failed or cancelled
         * run may never emit `_posthog/turn_complete`), or the stream errors out.
         */
        isThinking: [
            (s) => [s.runStarted, s.turnComplete, s.currentRunStatus, s.sseStatus],
            (runStarted, turnComplete, currentRunStatus, sseStatus): boolean =>
                runStarted && !turnComplete && !isTerminalRunStatus(currentRunStatus) && sseStatus !== 'error',
        ],
    }),
    listeners(({ values, actions, cache, props }) => ({
        bootstrapRun: async ({ taskId, runId, justCreatedRun }, breakpoint) => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            // Fresh-run fast path: nothing historical to assemble — go straight to SSE.
            if (justCreatedRun) {
                actions.openSseForRun({ taskId, runId, startLatest: false })
                return
            }

            // Existing run: replay the assembled resume-chain log, then refetch the run to decide on SSE.
            let entries: unknown[]
            try {
                entries = await api.tasks.runs.getLogEntries(taskId, runId)
            } catch (error) {
                actions.handleStreamError(mapHttpStatusToStreamError((error as { status?: number })?.status))
                return
            }
            breakpoint()
            // Flag history replay so re-derived permission requests restore card state without
            // re-firing telemetry. The forEach dispatches synchronously, so the flag can't leak
            // into live SSE ingestion.
            cache.bootstrapReplay = true
            try {
                entries.filter(isNotificationFrame).forEach((entry) => actions.ingestAcpFrame(entry))
            } finally {
                cache.bootstrapReplay = false
            }

            const result = await fetchRunStatus(taskId, runId)
            breakpoint()
            if ('error' in result) {
                actions.handleStreamError(result.error)
                return
            }
            if (isTerminalRunStatus(result.status)) {
                // Read-only history — surface the terminal status, do not open SSE. Flag the replay
                // so the listener records the status without re-emitting termination telemetry.
                actions.handleTerminalStatus({ status: result.status as SandboxRunStatus, replayedFromHistory: true })
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

            // Track the active run so the reconnect loop can refetch it on a drop.
            cache.activeRun = { taskId, runId }

            actions.sseConnecting()
            cache.disposables.dispose('reconnect-backoff')

            // Replace any prior connection.
            cache.disposables.dispose('event-source')
            // pauseOnPageHidden: false — a live SSE connection must survive tab hides; re-running
            // setup on show would replay the stream from the top and duplicate thread state.
            cache.disposables.add(
                (): (() => void) => {
                    const start = startLatest ? '?start=latest' : ''
                    const url = `/api/projects/${projectId}/tasks/${taskId}/runs/${runId}/stream/${start}`
                    const eventSource = new EventSource(url, { withCredentials: true })

                    eventSource.onopen = (): void => actions.sseOpened()
                    eventSource.onmessage = (event: MessageEvent<string>): void => {
                        let data: unknown
                        try {
                            data = JSON.parse(event.data)
                        } catch {
                            return
                        }
                        if (isNotificationFrame(data)) {
                            actions.ingestAcpFrame(data)
                        } else if (isPermissionRequestFrame(data)) {
                            // requestId-keyed dedup: the notification hash store doesn't cover this
                            // envelope, so a reconnect's full replay re-delivers it verbatim.
                            const record = parsePermissionRequestFrame(data)
                            if (
                                record &&
                                !values.seenPermissionRequestIds.has(record.requestId) &&
                                !values.resolvedPermissionRequestIds.has(record.requestId)
                            ) {
                                actions.routePermissionRequest(record)
                            }
                        } else if (isTaskRunStateFrame(data)) {
                            actions.handleTerminalStatus({
                                status: data.status as SandboxRunStatus,
                                errorMessage: data.error_message ?? null,
                            })
                        }
                        // keepalive arrives as a named event, never here; unknown frame types are ignored.
                    }
                    // `EventSource` fires `error` both for named `event: error` envelopes (carrying
                    // `data`) and for transient connection drops (no `data`). Surface the former
                    // verbatim; treat the latter as a drop and run the refetch + backoff loop.
                    eventSource.addEventListener('error', (event: MessageEvent<string>): void => {
                        if (typeof event.data === 'string' && event.data.length > 0) {
                            try {
                                const envelope: SseErrorFrameData = JSON.parse(event.data)
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
                },
                'event-source',
                { pauseOnPageHidden: false }
            )
        },
        sseDropped: async (_, breakpoint) => {
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            if (!activeRun) {
                return
            }
            // Stop the native EventSource so its built-in auto-retry doesn't race our loop.
            cache.disposables.dispose('event-source')

            // First refetch the run to detect terminal state.
            const result = await fetchRunStatus(activeRun.taskId, activeRun.runId)
            breakpoint()
            // The stream was closed or replaced while the refetch was in flight — drop this loop.
            if (cache.activeRun !== activeRun) {
                return
            }
            if ('error' in result) {
                actions.handleStreamError(result.error)
                return
            }

            // Terminal → final terminal-status action + close.
            if (isTerminalRunStatus(result.status)) {
                actions.handleTerminalStatus({ status: result.status as SandboxRunStatus })
                return
            }

            // Non-terminal → capped exponential backoff; attempts exhausted surface a retryable error.
            const attempt = values.reconnectAttempt + 1
            if (attempt > MAX_SSE_RECONNECT_ATTEMPTS) {
                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                return
            }
            actions.sseReconnecting(attempt)
            // pauseOnPageHidden: false — the SSE connection survives tab hides, so a drop in a
            // hidden tab must also reconnect there; a paused timer would stall until refocus.
            cache.disposables.add(
                (): (() => void) => {
                    const timer = window.setTimeout(() => {
                        // Reopen with a full replay (no start=latest): frames emitted while
                        // disconnected are re-delivered and the content-dedup drops the
                        // already-ingested ones, so the gap is filled losslessly.
                        actions.openSseForRun({ taskId: activeRun.taskId, runId: activeRun.runId, startLatest: false })
                    }, reconnectDelayMs(attempt))
                    return () => clearTimeout(timer)
                },
                'reconnect-backoff',
                { pauseOnPageHidden: false }
            )
        },
        routePermissionRequest: ({ record, replayedFromHistory }) => {
            // Replayed history is a read-only restore — never auto-approve (the run may be terminal).
            if (!replayedFromHistory && defaultPermissionDecision(record) === 'auto_allow') {
                const optionId = findAllowOptionId(record)
                if (optionId) {
                    actions.autoApprovePermissionRequest(record, optionId)
                    return
                }
            }
            actions.ingestPermissionRequest(record, replayedFromHistory)
        },
        autoApprovePermissionRequest: async ({ record, optionId }) => {
            // Pin it seen up front so a reconnect replay can't re-process the same request mid-POST.
            actions.markPermissionRequestSeen(record.requestId)
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            posthog.capture('permission_auto_approved', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                request_id: record.requestId,
                tool_call_name: record.rawToolCall.resolvedKey,
                tool_call_id: record.toolCallId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                execution_type: 'sandbox',
            })
            try {
                await api.conversations.permission(props.conversationId, {
                    requestId: record.requestId,
                    optionId,
                    traceId: values.traceId ?? undefined,
                })
                actions.markPermissionRequestResolved(record.requestId)
            } catch (error) {
                // The auto-approve POST failed — don't leave the agent silently blocked. Fall back to
                // the manual card so the user can respond.
                posthog.captureException(error)
                actions.ingestPermissionRequest(record)
            }
        },
        ingestPermissionRequest: ({ record, replayedFromHistory }) => {
            if (replayedFromHistory) {
                return
            }
            // conversation_id / trace_id are correlated by the caller (the SSE bypasses Django);
            // emit what this logic knows.
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            posthog.capture('permission_requested', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                request_id: record.requestId,
                tool_call_name: record.rawToolCall.resolvedKey,
                tool_call_id: record.toolCallId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                execution_type: 'sandbox',
            })
        },
        respondToPermission: async ({ conversationId, requestId, optionId, customInput }) => {
            try {
                // PERMISSION_RESPONDED telemetry is emitted server-side by the /permission/ handler;
                // forward the trace_id so it can correlate with the rest of this run's events.
                await api.conversations.permission(conversationId, {
                    requestId,
                    optionId,
                    customInput,
                    traceId: values.traceId ?? undefined,
                })
                actions.markPermissionRequestResolved(requestId)
            } catch (error) {
                // A failed reply POST does not mean the run died — the agent is still alive and
                // blocked on this same approval. Keep the failure local to the card (re-enable its
                // buttons for a retry) instead of tearing down the stream, which would release the
                // chat lock and hide the still-pending request behind the normal input.
                posthog.captureException(error)
                actions.permissionResponseFailed()
                lemonToast.error('Failed to send approval. Please try again.')
            }
        },
        handleTerminalStatus: ({ status, errorMessage, replayedFromHistory }) => {
            // The wire emits task_run_state for non-terminal transitions too (e.g. queued →
            // in_progress) — only an actually-terminal run has no more frames to stream.
            if (!isTerminalRunStatus(status)) {
                return
            }
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')

            // A run that already terminated in a prior session is surfaced read-only on reopen —
            // the reducers still record the terminal status, but re-emitting telemetry on every
            // page load would inflate termination counts.
            if (replayedFromHistory) {
                return
            }

            // TASK_RUN_TERMINATED telemetry. `duration_ms` is measured from the `_posthog/run_started`
            // frame; absent if the run terminated before one was seen.
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            const startedAt = cache.runStartedAtMs as number | undefined
            posthog.capture('task_run_terminated', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                status,
                error_message: errorMessage ?? undefined,
                execution_type: 'sandbox',
                duration_ms: startedAt !== undefined ? Date.now() - startedAt : undefined,
            })
        },
        closeSse: () => {
            cache.activeRun = undefined
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        reset: () => {
            cache.activeRun = undefined
            cache.runStartedAtMs = undefined
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        ingestAcpFrame: ({ entry }) => {
            const notification = entry?.notification
            if (!notification) {
                return
            }
            // Content-dedup: a reconnect with `?start=latest` may replay frames already folded in from
            // the `logs/` bootstrap (Redis-stream IDs aren't comparable to S3-log IDs). Match on
            // serialized JSON and drop repeats before they mutate thread state.
            const hash = hashLogEntry(entry)
            if (values.ingestedEntryHashes.has(hash)) {
                return
            }
            actions.markEntryIngested(hash)
            const method = notification.method

            // Custom `_posthog/*` notification namespace emitted by the agent-server.
            if (method === '_posthog/run_started') {
                // TASK_RUN_STARTED telemetry — emit once per run on the first `_posthog/run_started`
                // frame. `cold_start` is true unless the run was pre-warmed. Suppressed while
                // replaying history (the run started in a prior session) — `markRunStarted` below
                // still runs so the thread's started/thinking state stays correct.
                if (!values.runStarted && cache.bootstrapReplay !== true) {
                    const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
                    cache.runStartedAtMs = Date.now()
                    posthog.capture('task_run_started', {
                        conversation_id: props.conversationId,
                        trace_id: values.traceId,
                        run_id: activeRun?.runId,
                        task_id: activeRun?.taskId,
                        execution_type: 'sandbox',
                        // The run-started frame carries no warmth signal and pre-warming isn't wired
                        // yet, so every run is a cold start. A later pre-warm hook flips this.
                        cold_start: true,
                    })
                }
                actions.markRunStarted()
                return
            }
            if (method === '_posthog/turn_complete') {
                actions.markTurnComplete()
                return
            }
            if (method === '_posthog/progress') {
                const progress = (notification.params ?? {}) as PosthogProgressParams
                actions.setCurrentProgress(String(progress.label ?? progress.detail ?? ''))
                return
            }
            if (method === '_posthog/error') {
                const error = (notification.params ?? {}) as PosthogErrorParams
                actions.pushErrorItem(String(error.message ?? notification.error?.message ?? 'Agent error'))
                return
            }
            // The agent-server persists the permission lifecycle to the run log as these two
            // notifications — pending approvals are re-derived from them on bootstrap (a reload
            // mid-approval would otherwise lose the card while the agent stays blocked), and a
            // resolution observed here (e.g. answered in another tab) clears the local card.
            if (isPosthogNotification(notification, '_posthog/permission_request')) {
                const record = parsePermissionRequestFrame(notification.params ?? {})
                if (
                    record &&
                    !values.seenPermissionRequestIds.has(record.requestId) &&
                    !values.resolvedPermissionRequestIds.has(record.requestId)
                ) {
                    actions.routePermissionRequest(record, cache.bootstrapReplay === true)
                }
                return
            }
            if (isPosthogNotification(notification, '_posthog/permission_resolved')) {
                const requestId = notification.params?.requestId
                if (typeof requestId === 'string' && requestId) {
                    actions.markPermissionRequestResolved(requestId)
                }
                return
            }
            if (method?.startsWith('_posthog/')) {
                // _posthog/usage_update, _posthog/console, _posthog/sdk_session, _posthog/git_checkpoint, ...
                return
            }

            if (!isSessionUpdateNotification(notification)) {
                return
            }

            const update = notification.params?.update
            if (!isKnownSessionUpdate(update)) {
                return
            }

            switch (update.sessionUpdate) {
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
                case 'agent_thought_chunk': {
                    // No messageId on the wire — all thought chunks share a fallback id distinct
                    // from the assistant-message fallback so the two buffers never collide on a key.
                    const id = String(update.messageId ?? 'current-thought')
                    actions.appendThoughtChunk(id, String(update.content?.text ?? update.text ?? ''))
                    break
                }
                case 'tool_call': {
                    const toolCallId = String(update.toolCallId ?? '')
                    if (!toolCallId) {
                        break
                    }
                    const rawServerName = String(update.serverName ?? 'posthog')
                    const rawToolName = String(update.toolName ?? update.title ?? '')
                    const input = update.rawInput ?? update.input ?? {}
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
                        title: update.title,
                        kind: update.kind,
                        locations: update.locations,
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
                    const status = mapAcpStatus(update.status ?? existing?.status)
                    const errorMessage =
                        update.error?.message ?? (status === 'failed' ? notification.error?.message : undefined)
                    // The tool's args stream in across updates (e.g. an `exec` command or a tool's
                    // input building up), so fold the latest rawInput in and re-resolve the registry
                    // key from it rather than freezing the empty input the initial tool_call carried.
                    // Keep the runtime object checks — the wire payload is typed, not validated.
                    const rawInput =
                        update.rawInput && typeof update.rawInput === 'object'
                            ? update.rawInput
                            : update.input && typeof update.input === 'object'
                              ? update.input
                              : undefined
                    const reResolved =
                        rawInput && existing
                            ? resolveToolKey(existing.rawServerName, existing.rawToolName, rawInput)
                            : undefined
                    actions.updateToolInvocation(toolCallId, {
                        status,
                        title: update.title ?? existing?.title,
                        progress: update.progress ?? existing?.progress,
                        output: update.rawOutput ?? existing?.output,
                        locations: update.locations ?? existing?.locations,
                        contentBlocks: mergedContent,
                        error: errorMessage !== undefined ? { message: errorMessage } : existing?.error,
                        ...(rawInput ? { input: rawInput } : {}),
                        ...(reResolved
                            ? {
                                  resolvedKey: reResolved.resolvedKey,
                                  innerToolName: reResolved.innerToolName,
                                  innerInput: reResolved.innerInput,
                              }
                            : {}),
                    })
                    // TOOL_CALL_COMPLETED telemetry (optional) — emit once when a tool call first
                    // transitions to a terminal status. `duration_ms` is measured from the run start
                    // since per-tool start timing isn't carried on the wire. Suppressed while
                    // replaying history so a reopen doesn't re-count tool calls from a prior session.
                    if (
                        cache.bootstrapReplay !== true &&
                        (status === 'completed' || status === 'failed') &&
                        existing?.status !== 'completed' &&
                        existing?.status !== 'failed'
                    ) {
                        const startedAt = cache.runStartedAtMs as number | undefined
                        posthog.capture('tool_call_completed', {
                            conversation_id: props.conversationId,
                            trace_id: values.traceId,
                            tool_call_id: toolCallId,
                            tool_qualified_name: existing?.resolvedKey,
                            status,
                            duration_ms: startedAt !== undefined ? Date.now() - startedAt : undefined,
                            execution_type: 'sandbox',
                        })
                    }
                    break
                }
                case 'current_mode_update': {
                    actions.setCurrentMode(String(update.currentModeId ?? update.mode ?? ''))
                    break
                }
            }
        },
    })),
])
