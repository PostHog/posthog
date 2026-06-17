import { actions, afterMount, connect, kea, key, listeners, path, props, reducers, selectors } from 'kea'
import posthog from 'posthog-js'

import api from 'lib/api'
import { lemonToast } from 'lib/lemon-ui/LemonToast'
import { projectLogic } from 'scenes/projectLogic'

import { tasksRunsCommandCreate } from 'products/tasks/frontend/generated/api'

import type { sandboxStreamLogicType } from './sandboxStreamLogicType'
import { defaultPermissionDecision, findAllowOptionId } from './sandboxToolPolicy'
import type {
    ContextUsage,
    PermissionRequestRecord,
    ResourceProduct,
    SdkSession,
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
    type PosthogUsageUpdateParams,
    type SessionUpdateUsage,
    type SseErrorFrameData,
    type StoredLogEntry,
    isKnownSessionUpdate,
    isNotificationFrame,
    isPermissionRequestFrame,
    isPosthogNotification,
    isSessionUpdateNotification,
    isSessionUpdateUsage,
    isSessionUpdateUserMessage,
    isTaskRunStateFrame,
} from './types/sandboxWireTypes'

export type SandboxSseStatus = 'idle' | 'connecting' | 'open' | 'reconnecting' | 'closed' | 'error'
export type SandboxRunStatus = 'queued' | 'in_progress' | 'completed' | 'failed' | 'cancelled'

export interface SandboxStreamLogicProps {
    /**
     * Stable logic key. PostHog AI passes the conversation id; a generic task viewer (no conversation)
     * passes the task id. The logic operates on `(taskId, runId)` internally, so it never needs the
     * conversation beyond this key and the optional telemetry tag below.
     */
    streamKey: string
    /** Optional telemetry tag — present for PostHog AI conversations, absent for a generic task viewer. */
    conversationId?: string
}

/** Reconnect/backoff constants for the SSE drop-recovery loop. */
export const MAX_SSE_RECONNECT_ATTEMPTS = 5
export const SSE_RECONNECT_BASE_DELAY_MS = 2_000
export const SSE_RECONNECT_MAX_DELAY_MS = 30_000
/**
 * Cumulative cap across all drops in a run — bounds runaway clean-EOF loops that keep dodging the
 * per-drop counter (a connection that opens, immediately drops, and reopens resets `reconnectAttempt`
 * to 0 every cycle, so only this counter catches the loop).
 */
export const MAX_CUMULATIVE_RECONNECT_ATTEMPTS = 30
/** A connection open at least this long before dropping is healthy — its drop is forgiven. */
export const SSE_HEALTHY_CONNECTION_MS = 60_000

/** The crash-error string the in-sandbox agent server writes on a fatal exception. */
const AGENT_CRASH_PREFIX = 'Agent server crashed'

const TERMINAL_RUN_STATUSES: ReadonlySet<string> = new Set(['completed', 'failed', 'cancelled'])

export function isTerminalRunStatus(status: string | null | undefined): boolean {
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

/**
 * Content-dedup identity for a StoredLogEntry. Hashes only the `notification` body and drops the
 * top-level `timestamp`: the `logs/` (S3) copy and the live re-broadcast are independent writes
 * that stamp their own per-write timestamps, so a timestamp-inclusive hash would miss the duplicate
 * and double-append the same logical frame on a reconnect replay.
 */
function hashLogEntry(entry: StoredLogEntry): string {
    return JSON.stringify(entry.notification)
}

/**
 * Recovers the raw text the user typed from a persisted `_posthog/user_message`. The backend
 * prepends a `<posthog_context>…</posthog_context>` block when attachments are present
 * (`context_wrapper.wrap_user_message`); stripping it keeps a replayed prompt identical to the one
 * the live send path echoed via `pushHumanMessage`.
 */
function unwrapUserMessageContent(content: string): string {
    const closeTag = '</posthog_context>'
    if (content.startsWith('<posthog_context>')) {
        const closeIdx = content.indexOf(closeTag)
        if (closeIdx !== -1) {
            return content.slice(closeIdx + closeTag.length).replace(/^\n+/, '')
        }
    }
    return content
}

/**
 * Pull rendered text out of a `_posthog/user_message` frame's `content`. The seeder writes a plain
 * string; the live wire may instead carry ACP content blocks (`[{ type: 'text', text }]`). Returns
 * the concatenated text, or '' when there's nothing renderable.
 */
function extractUserMessageText(content: string | unknown[] | undefined): string {
    if (typeof content === 'string') {
        return content
    }
    if (Array.isArray(content)) {
        return content
            .map((block) =>
                block && typeof block === 'object' && typeof (block as { text?: unknown }).text === 'string'
                    ? (block as { text: string }).text
                    : ''
            )
            .join('')
    }
    return ''
}

/**
 * Union incoming resource products into the accumulated list by `id`, preserving first-seen order.
 * Pure — mirrors the reference `accumulateSessionResources`. Products without an `id` are skipped.
 */
export function mergeResourceProducts(
    existing: ResourceProduct[],
    incoming: { id?: string; label?: string }[]
): ResourceProduct[] {
    const seen = new Set(existing.map((p) => p.id))
    const next = [...existing]
    for (const product of incoming) {
        if (typeof product.id !== 'string' || product.id === '' || seen.has(product.id)) {
            continue
        }
        seen.add(product.id)
        next.push({ id: product.id, label: product.label })
    }
    return next
}

/** Normalize either wire cost shape (a bare number, or `{amount, currency}`) to a number | undefined. */
function normalizeUsageCost(
    cost: number | { amount?: number; currency?: string } | null | undefined
): number | undefined {
    if (cost == null) {
        return undefined
    }
    if (typeof cost === 'number') {
        return cost
    }
    return typeof cost.amount === 'number' ? cost.amount : undefined
}

/** Latest-wins fold of an `_posthog/usage_update` ext-notification onto the context-usage snapshot. */
export function foldUsageNotification(existing: ContextUsage | null, params: PosthogUsageUpdateParams): ContextUsage {
    const next: ContextUsage = { ...existing }
    if (params.used != null) {
        next.tokens = params.used
    }
    if (params.breakdown != null) {
        next.breakdown = params.breakdown
    }
    const cost = normalizeUsageCost(params.cost)
    if (cost !== undefined) {
        next.cost = cost
    }
    return next
}

/** Latest-wins fold of the numeric `session/update` usage aggregate (drives the percentage ring). */
export function foldUsageAggregate(existing: ContextUsage | null, update: SessionUpdateUsage): ContextUsage {
    const next: ContextUsage = { ...existing }
    if (typeof update.used === 'number') {
        next.used = update.used
    }
    if (typeof update.size === 'number') {
        next.size = update.size
    }
    const cost = normalizeUsageCost(update.cost)
    if (cost !== undefined) {
        next.cost = cost
    }
    return next
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

/** Reads `_meta.claudeCode` off a tool frame's `_meta` without trusting its shape. */
function getClaudeCodeMeta(meta: unknown): Record<string, unknown> | undefined {
    if (typeof meta !== 'object' || meta === null) {
        return undefined
    }
    const claudeCode = (meta as { claudeCode?: unknown }).claudeCode
    return typeof claudeCode === 'object' && claudeCode !== null ? (claudeCode as Record<string, unknown>) : undefined
}

/** Stable SDK tool name (`"Edit"`, `"TodoWrite"`) from `_meta.claudeCode.toolName`; undefined when absent. */
export function extractClaudeToolName(meta: unknown): string | undefined {
    const claudeCode = getClaudeCodeMeta(meta)
    return typeof claudeCode?.toolName === 'string' && claudeCode.toolName ? claudeCode.toolName : undefined
}

/**
 * Permission-denial reason from `_meta.claudeCode.toolResponse`, preferring `decisionReason` over
 * the generic `message`. Returns undefined when no `_meta` is present (the inline `canUseTool` path),
 * so the caller can fall back to the content text / existing error.
 */
export function extractDenialReason(meta: unknown): string | undefined {
    const claudeCode = getClaudeCodeMeta(meta)
    const toolResponse = claudeCode?.toolResponse
    if (typeof toolResponse !== 'object' || toolResponse === null) {
        return undefined
    }
    const r = toolResponse as { decisionReason?: unknown; message?: unknown }
    if (typeof r.decisionReason === 'string' && r.decisionReason) {
        return r.decisionReason
    }
    if (typeof r.message === 'string' && r.message) {
        return r.message
    }
    return undefined
}

/**
 * Resolves the registry key for a tool call. The single-exec `posthog` MCP server exposes one
 * outer `exec` tool; the inner tool name is parsed out of `rawInput.command`. Non-exec MCP tools
 * and Claude built-ins look up by their wire name directly. Claude built-ins carry no wire
 * `toolName`, so `claudeToolName` (from `_meta.claudeCode.toolName`) is preferred as the fallback.
 */
export function resolveToolKey(
    serverName: string,
    toolName: string,
    input: Record<string, unknown>,
    claudeToolName?: string
): ResolvedToolKey {
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

    return { resolvedKey: toolName || claudeToolName || '' }
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

/** The in-progress compaction spinner item — cleared when compaction completes or a boundary lands. */
function isPendingCompactingStatus(item: ThreadItem): boolean {
    return item.type === 'status' && item.status === 'compacting' && item.isComplete !== true
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
    // MCP-tool approval frames stamp the inner SDK tool name under `_meta.claudeCode.toolName`; pass
    // it through so the card names the inner tool. No-op when absent (the field may not be present yet).
    const claudeToolName = extractClaudeToolName(toolCall._meta)
    const wireToolName = String(toolCall.toolName ?? '')
    const rawToolName = wireToolName || (claudeToolName ? '' : String(toolCall.title ?? ''))
    const input = (toolCall.rawInput ?? toolCall.input ?? {}) as Record<string, unknown>
    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(
        rawServerName,
        wireToolName,
        input,
        claudeToolName
    )

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
            claudeToolName,
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
 * Keyed by `streamKey` (the conversation id for PostHog AI, the task id for a generic task viewer)
 * so concurrent streams keep independent stream state and EventSource connections.
 */
export const sandboxStreamLogic = kea<sandboxStreamLogicType>([
    props({} as SandboxStreamLogicProps),
    key((props) => props.streamKey),
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
        respondToPermission: (payload: { requestId: string; optionId: string; customInput?: string }) => payload,
        clearPermissionRequest: true,
        /**
         * Cancel a run via the generic tasks relay. With no argument, cancels the streamed run
         * (`cache.activeRun`); pass an explicit run to cancel a warm Run the renderer isn't streaming.
         */
        cancelRun: (run?: { taskId: string; runId: string }) => ({ run }),
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
        /** Optional `task_run_state.stage` — wired for a future richer status surface (G6). */
        setCurrentStage: (stage: string | null) => ({ stage }),
        markRunStarted: true,
        markTurnComplete: true,
        /** Echoes the user's own message into the thread — the sandbox wire never replays it. */
        pushHumanMessage: (content: string) => ({ content }),
        pushErrorItem: (errorMessage: string, variant: 'error' | 'crash' = 'error') => ({ errorMessage, variant }),
        /** Union the products an answer was grounded in — accumulates across the whole session. */
        mergeResourcesUsed: (products: { id?: string; label?: string }[]) => ({ products }),
        /** Latest-wins context-usage snapshot fold (token/cost/breakdown or numeric aggregate). */
        setContextUsage: (usage: ContextUsage) => ({ usage }),
        /** Inline `_posthog/status` thread item (e.g. compaction in progress). */
        pushStatusItem: (status: string, isComplete: boolean) => ({ status, isComplete }),
        /** Removes the in-progress compaction spinner once compaction completes. */
        clearCompactingStatus: true,
        /** Inline `_posthog/compact_boundary` thread item — the post-compaction marker. */
        pushCompactBoundaryItem: (payload: { trigger?: string; preTokens?: number; contextSize?: number }) => payload,
        /** Inline `_posthog/task_notification` thread item — a task milestone. */
        pushTaskNotificationItem: (payload: { status?: string; summary?: string }) => payload,
        /** Diagnostic `_posthog/sdk_session` plumbing — no UI. */
        setSdkSession: (session: SdkSession) => ({ session }),
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
        // Counts every drop in the run regardless of the per-drop counter (healthy-connection drops
        // don't bump `reconnectAttempt`, and a clean-EOF reopen loop keeps resetting it). Bounds
        // runaway loops via MAX_CUMULATIVE_RECONNECT_ATTEMPTS. Cleared only on a fresh bootstrap.
        cumulativeReconnectAttempt: [
            0,
            {
                sseReconnecting: (state) => state + 1,
                bootstrapRun: () => 0,
                reset: () => 0,
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
                pushErrorItem: (state, { errorMessage, variant }) => [
                    ...state,
                    { id: `error-${state.length}`, type: 'error', errorMessage, variant },
                ],
                pushStatusItem: (state, { status, isComplete }) => [
                    ...state,
                    { id: `status-${state.length}`, type: 'status', status, isComplete },
                ],
                clearCompactingStatus: (state) => state.filter((item) => !isPendingCompactingStatus(item)),
                // Drop the in-progress spinner before the divider lands, in case the completing
                // status frame never arrived — the boundary itself signals compaction is done.
                pushCompactBoundaryItem: (state, { trigger, preTokens, contextSize }) => [
                    ...state.filter((item) => !isPendingCompactingStatus(item)),
                    { id: `compact-${state.length}`, type: 'compact_boundary', trigger, preTokens, contextSize },
                ],
                pushTaskNotificationItem: (state, { status, summary }) => [
                    ...state,
                    { id: `task-${state.length}`, type: 'task_notification', status, summary },
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
        // Optional `task_run_state.stage` — generally unset for PHAI runs, but cheap to track so a
        // future richer status surface (G6) can render "research / plan / build" without re-touching
        // this logic. No render consumes it yet.
        currentStage: [
            null as string | null,
            {
                setCurrentStage: (_, { stage }) => stage,
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
                // A run emits `_posthog/run_started` once; a follow-up message on the same run starts
                // a fresh turn with no new run_started frame, so a human message also reopens the
                // turn — otherwise the thinking indicator would stay off for the whole follow-up.
                markRunStarted: () => false,
                pushHumanMessage: () => false,
                reset: () => false,
            },
        ],
        // Products the agent grounded answers in, unioned by id (first-seen order) across the whole
        // session. NOT cleared on markTurnComplete — the bar accumulates; only a reset clears it.
        resourcesUsed: [
            [] as ResourceProduct[],
            {
                mergeResourcesUsed: (state, { products }) => mergeResourceProducts(state, products),
                reset: () => [],
            },
        ],
        // Latest-wins context-usage snapshot for the footer ring. The setContextUsage payload is the
        // already-folded snapshot (the listener merges onto the prior value).
        contextUsage: [
            null as ContextUsage | null,
            {
                setContextUsage: (_, { usage }) => usage,
                reset: () => null,
            },
        ],
        // Diagnostic resume plumbing — adapter/session identity for telemetry. No UI.
        sdkSession: [
            null as SdkSession | null,
            {
                setSdkSession: (_, { session }) => session,
                reset: () => null,
            },
        ],
    }),
    selectors({
        /**
         * Whether the agent is actively working a turn — drives the thread's thinking indicator.
         * Off once the turn completes, the run reaches a terminal status (a failed or cancelled
         * run may never emit `_posthog/turn_complete`), or the stream errors out.
         *
         * A run is "in flight" from the moment it is `queued` — keying off `currentRunStatus` as
         * well as `runStarted` lights the indicator during the multi-second cold-boot window before
         * the first `_posthog/run_started` frame, which `runStarted` alone misses.
         */
        isThinking: [
            (s) => [s.runStarted, s.turnComplete, s.currentRunStatus, s.sseStatus],
            (runStarted, turnComplete, currentRunStatus, sseStatus): boolean => {
                if (sseStatus === 'error' || isTerminalRunStatus(currentRunStatus)) {
                    return false
                }
                const runInFlight = runStarted || currentRunStatus === 'queued' || currentRunStatus === 'in_progress'
                return runInFlight && !turnComplete
            },
        ],
        /**
         * Stream lifecycle phase for the pre-first-message status line. `provisioning` = the stream
         * is opening or open but the agent hasn't started yet (the workflow is still setting up the
         * sandbox and emitting `_posthog/progress`), so the thinking indicator's `run_started` gate
         * would otherwise hide that progress; `thinking` = the agent is working a turn (mirrors
         * `isThinking`); `idle` otherwise (terminal, errored, or not yet connecting).
         */
        streamPhase: [
            (s) => [s.runStarted, s.isThinking, s.currentRunStatus, s.sseStatus],
            (runStarted, isThinking, currentRunStatus, sseStatus): 'provisioning' | 'thinking' | 'idle' => {
                if (isThinking) {
                    return 'thinking'
                }
                const connecting = sseStatus === 'connecting' || sseStatus === 'open' || sseStatus === 'reconnecting'
                if (connecting && !runStarted && !isTerminalRunStatus(currentRunStatus)) {
                    return 'provisioning'
                }
                return 'idle'
            },
        ],
    }),
    listeners(({ values, actions, cache, props }) => ({
        bootstrapRun: async ({ taskId, runId, justCreatedRun }, breakpoint) => {
            const projectId = values.currentProjectId
            if (projectId === null) {
                actions.handleStreamError({ errorTitle: 'No current project', retryable: false })
                return
            }

            // Persistent provisioning flag for disconnect telemetry: stays true across the async
            // gap between bootstrap and the first connection/run_started, unlike `cache.bootstrapReplay`
            // (which is only true inside the synchronous history-replay forEach). Cleared on the first
            // `sseOpened`/`_posthog/run_started`.
            cache.isBootstrapping = true

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
                            // `stage` is dropped by handleTerminalStatus's status-only path; track it
                            // separately for a future richer status surface. Generally unset for PHAI.
                            if (data.stage !== undefined) {
                                actions.setCurrentStage(data.stage ?? null)
                            }
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
        sseOpened: () => {
            // Provisioning ends at the first successful connection; clear the flag the disconnect
            // telemetry reads. Stamp the connection time for the healthy-connection rule in sseDropped.
            cache.isBootstrapping = false
            cache.sseConnectedAtMs = Date.now()
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

            // Cumulative cap — bounds runaway clean-EOF reopen loops that keep resetting the per-drop
            // counter. The about-to-be-scheduled reconnect is the (cumulative + 1)th.
            if (values.cumulativeReconnectAttempt + 1 > MAX_CUMULATIVE_RECONNECT_ATTEMPTS) {
                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                return
            }

            // Healthy-connection rule — a connection that stayed open ≥60s before dropping is not a
            // flaky transport, so its drop is forgiven: schedule a reconnect but don't grow the
            // per-drop budget. The cumulative counter still increments (via sseReconnecting) to
            // bound pathological reopen loops.
            const connectedAtMs = cache.sseConnectedAtMs as number | undefined
            const wasHealthy = connectedAtMs !== undefined && Date.now() - connectedAtMs >= SSE_HEALTHY_CONNECTION_MS

            // Non-terminal → capped exponential backoff; attempts exhausted surface a retryable error.
            const attempt = wasHealthy ? values.reconnectAttempt : values.reconnectAttempt + 1
            if (attempt > MAX_SSE_RECONNECT_ATTEMPTS) {
                actions.handleStreamError({ errorTitle: 'Cloud stream failed', retryable: true })
                return
            }
            // Backoff off the per-drop budget; a forgiven healthy drop (attempt 0) reconnects fast.
            const delayMs = reconnectDelayMs(Math.max(attempt, 1))
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
                    }, delayMs)
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
            if (!activeRun || values.currentProjectId == null) {
                // No active run to command yet — fall back to the manual card so the user can respond.
                actions.ingestPermissionRequest(record)
                return
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), activeRun.taskId, activeRun.runId, {
                    jsonrpc: '2.0',
                    method: 'permission_response',
                    params: { requestId: record.requestId, optionId },
                })
                actions.markPermissionRequestResolved(record.requestId)
            } catch (error) {
                // The auto-approve command failed — don't leave the agent silently blocked. Fall back to
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
        respondToPermission: async ({ requestId, optionId, customInput }) => {
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            if (!activeRun || values.currentProjectId == null) {
                // No live run to command — keep the card so the user can retry once the stream resolves.
                actions.permissionResponseFailed()
                lemonToast.error('Failed to send approval. Please try again.')
                return
            }
            try {
                // PERMISSION_RESPONDED telemetry is emitted server-side by the tasks relay. The renderer
                // commands the run it is streaming (`cache.activeRun`); on a persistent sandbox the run
                // only advances when the old one dies and the successor takes over — which is exactly the
                // run the renderer has re-resolved, so the reply lands where it belongs.
                await tasksRunsCommandCreate(String(values.currentProjectId), activeRun.taskId, activeRun.runId, {
                    jsonrpc: '2.0',
                    method: 'permission_response',
                    params: { requestId, optionId, customInput },
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
        cancelRun: async ({ run }) => {
            // Cancel a run through the generic tasks relay — the same command PostHog Code issues. The
            // SSE then receives a terminal task_run_state; cancellation telemetry is emitted server-side
            // by the relay. `run` defaults to the streamed run; a warm Run (not streamed) is passed in.
            // Fire-and-forget: a failure leaves the run alive for a retry.
            const target = run ?? (cache.activeRun as { taskId: string; runId: string } | undefined)
            if (!target || values.currentProjectId == null) {
                return
            }
            try {
                await tasksRunsCommandCreate(String(values.currentProjectId), target.taskId, target.runId, {
                    jsonrpc: '2.0',
                    method: 'cancel',
                })
            } catch (error) {
                posthog.captureException(error)
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

            // Crash/failure affordance: a failed run carrying an error_message otherwise just blanks
            // the thinking indicator. Push a visible error item so the user sees why it stopped. The
            // in-sandbox agent server writes "Agent server crashed: …" on a fatal exception — render
            // that as a friendlier, retry-oriented `crash` variant; other failures show the raw line.
            if (status === 'failed' && errorMessage) {
                actions.pushErrorItem(errorMessage, errorMessage.startsWith(AGENT_CRASH_PREFIX) ? 'crash' : 'error')
            }

            // TASK_RUN_TERMINATED telemetry. `duration_ms` is measured from the current turn's start
            // (run start for the first turn, the latest human message for a follow-up); absent if the
            // run terminated before either was seen.
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            const startedAt = cache.turnStartedAtMs as number | undefined
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
        handleStreamError: ({ errorTitle, errorMessage, retryable }) => {
            // The composer-unlock is already wired off this action in maxThreadLogic; today it
            // unlocks silently. Push a visible, retryable error line so the user knows the stream
            // dropped — and capture the disconnect telemetry that mirrors the cloud client's
            // CLOUD_STREAM_DISCONNECTED (the relay can't see a client-side reconnect-budget exhaustion).
            actions.pushErrorItem(errorMessage ? `${errorTitle}: ${errorMessage}` : errorTitle)
            const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
            posthog.capture('sandbox_stream_disconnected', {
                conversation_id: props.conversationId,
                trace_id: values.traceId,
                run_id: activeRun?.runId,
                task_id: activeRun?.taskId,
                error_title: errorTitle,
                retryable,
                reconnect_attempts: values.reconnectAttempt,
                stream_error_attempts: 0,
                cumulative_reconnect_attempts: values.cumulativeReconnectAttempt,
                was_bootstrapping: cache.isBootstrapping === true,
                execution_type: 'sandbox',
            })
        },
        closeSse: () => {
            cache.activeRun = undefined
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        reset: () => {
            cache.activeRun = undefined
            cache.turnStartedAtMs = undefined
            cache.ingestedEntryHashes = new Set<string>()
            cache.isBootstrapping = false
            cache.sseConnectedAtMs = undefined
            cache.disposables.dispose('reconnect-backoff')
            cache.disposables.dispose('event-source')
        },
        pushHumanMessage: () => {
            // Stamp the start of the turn this message opens, so per-turn duration metrics on a
            // follow-up aren't measured from the first turn's start. Skipped while replaying history
            // (the stamp would be "now", not the historical turn time, and replay emits no telemetry).
            if (cache.bootstrapReplay !== true) {
                cache.turnStartedAtMs = Date.now()
            }
        },
        ingestAcpFrame: ({ entry }) => {
            const notification = entry?.notification
            if (!notification) {
                return
            }
            // Content-dedup: a reconnect with `?start=latest` may replay frames already folded in from
            // the `logs/` bootstrap (Redis-stream IDs aren't comparable to S3-log IDs). Match on the
            // serialized notification body and drop repeats before they mutate thread state. The hash
            // set lives in a mutable cache ref (not a reducer) so the streaming hot path stays O(1)
            // per frame instead of copying a growing Set on every token chunk.
            if (!cache.ingestedEntryHashes) {
                cache.ingestedEntryHashes = new Set<string>()
            }
            const ingestedHashes = cache.ingestedEntryHashes as Set<string>
            const hash = hashLogEntry(entry)
            if (ingestedHashes.has(hash)) {
                return
            }
            ingestedHashes.add(hash)
            const method = notification.method

            // Custom `_posthog/*` notification namespace emitted by the agent-server.
            if (method === '_posthog/run_started') {
                // TASK_RUN_STARTED telemetry — emit once per run on the first `_posthog/run_started`
                // frame. `cold_start` is true unless the run was pre-warmed. Suppressed while
                // replaying history (the run started in a prior session) — `markRunStarted` below
                // still runs so the thread's started/thinking state stays correct.
                if (!values.runStarted && cache.bootstrapReplay !== true) {
                    const activeRun = cache.activeRun as { taskId: string; runId: string } | undefined
                    cache.turnStartedAtMs = Date.now()
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
                // Provisioning is over once the agent has started — clear the disconnect-telemetry flag.
                cache.isBootstrapping = false
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
            // Seeded / persisted user turns. Live messages are already echoed into the thread by
            // maxThreadLogic (`pushSandboxHumanMessage`) the moment they're sent, so only render this
            // frame on `logs/` bootstrap replay — otherwise a live turn would render the user's
            // message twice (once on send, once when the relay echoes the command back). This is also
            // the only path that surfaces a converted LangGraph thread's human turns.
            if (isPosthogNotification(notification, '_posthog/user_message')) {
                if (cache.bootstrapReplay === true) {
                    const text = extractUserMessageText(notification.params?.content)
                    // Persisted prompts may carry the `<posthog_context>…</posthog_context>` wrapper
                    // added when attachments are present; strip it so a replayed prompt matches the
                    // live one.
                    const unwrapped = unwrapUserMessageContent(text)
                    if (unwrapped) {
                        actions.pushHumanMessage(unwrapped)
                    }
                }
                return
            }
            // The agent reports, per turn, which PostHog products an answer was grounded in. Union
            // them by id into the persistent resources bar — accumulates across the whole session.
            if (isPosthogNotification(notification, '_posthog/resources_used')) {
                actions.mergeResourcesUsed(notification.params?.products ?? [])
                return
            }
            // Token usage + cost + context-window breakdown. The Codex adapter sends two split
            // frames; the Claude adapter sends a single combined frame (used + cost-as-number +
            // breakdown). The permissive fold tolerates both. The numeric used/size aggregate that
            // drives the percentage ring arrives separately on a session/update (handled below).
            if (isPosthogNotification(notification, '_posthog/usage_update')) {
                actions.setContextUsage(foldUsageNotification(values.contextUsage, notification.params ?? {}))
                return
            }
            // Context-compaction start/end. The in-progress frame pushes a spinner item; the
            // completed frame clears that spinner (Twig renders nothing for the completed case)
            // rather than leaving it hanging beside the `compact_boundary` divider that follows.
            if (isPosthogNotification(notification, '_posthog/status')) {
                const status = String(notification.params?.status ?? '')
                const isComplete = notification.params?.isComplete === true
                if (status === 'compacting' && isComplete) {
                    actions.clearCompactingStatus()
                    return
                }
                actions.pushStatusItem(status, isComplete)
                return
            }
            if (isPosthogNotification(notification, '_posthog/compact_boundary')) {
                const params = notification.params
                actions.pushCompactBoundaryItem({
                    trigger: params?.trigger,
                    preTokens: params?.preTokens,
                    contextSize: params?.contextSize,
                })
                return
            }
            if (isPosthogNotification(notification, '_posthog/task_notification')) {
                const params = notification.params
                actions.pushTaskNotificationItem({ status: params?.status, summary: params?.summary })
                return
            }
            // Diagnostic only — no UI; kept for resume telemetry / crash-affordance work.
            if (isPosthogNotification(notification, '_posthog/sdk_session')) {
                const params = notification.params
                actions.setSdkSession({ sessionId: params?.sessionId, adapter: params?.adapter })
                return
            }
            if (method?.startsWith('_posthog/')) {
                // _posthog/console, _posthog/sandbox_output, _posthog/git_checkpoint, ... — still dropped.
                return
            }

            if (!isSessionUpdateNotification(notification)) {
                return
            }

            const update = notification.params?.update
            // The numeric used/size usage aggregate is session/update-framed but isn't in
            // KNOWN_SESSION_UPDATES — special-case it before isKnownSessionUpdate to drive the ring
            // without widening the tool-render switch below.
            if (isSessionUpdateUsage(update)) {
                actions.setContextUsage(foldUsageAggregate(values.contextUsage, update))
                return
            }
            // The user's own turn is persisted to the run log as a `session/update`
            // (`user_message_chunk`), so this is what restores human turns when a thread loads from
            // `logs/`. Render it only on bootstrap replay — a live turn is already echoed into the
            // thread by maxThreadLogic (`pushSandboxHumanMessage`) on send, so rendering the wire echo
            // too would duplicate it. (The legacy `_posthog/user_message` handler above covers an
            // older frame shape the backend no longer emits.)
            if (isSessionUpdateUserMessage(update)) {
                if (cache.bootstrapReplay === true) {
                    const text = String(update.content?.text ?? update.text ?? '')
                    const unwrapped = unwrapUserMessageContent(text)
                    if (unwrapped) {
                        actions.pushHumanMessage(unwrapped)
                    }
                }
                return
            }
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
                    const claudeToolName = extractClaudeToolName(update._meta)
                    const wireToolName = String(update.toolName ?? '')
                    // `rawToolName` is the displayed name (wire name, or the human title for built-ins
                    // that carry no name); the resolver keys off the wire name + SDK name instead.
                    const rawToolName = wireToolName || (claudeToolName ? '' : String(update.title ?? ''))
                    const input = update.rawInput ?? update.input ?? {}
                    const { resolvedKey, innerToolName, innerInput } = resolveToolKey(
                        rawServerName,
                        wireToolName,
                        input,
                        claudeToolName
                    )
                    actions.upsertToolInvocation({
                        toolCallId,
                        rawServerName,
                        rawToolName,
                        innerToolName,
                        resolvedKey,
                        claudeToolName,
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
                    const status = mapAcpStatus(update.status ?? existing?.status)
                    // Keep the runtime object checks — the wire payload is typed, not validated.
                    const rawInput =
                        update.rawInput && typeof update.rawInput === 'object'
                            ? update.rawInput
                            : update.input && typeof update.input === 'object'
                              ? update.input
                              : undefined
                    // On a permission denial Twig stamps the reason under `_meta.claudeCode.toolResponse`;
                    // prefer it for the error when the update carries no explicit error, and fall back to
                    // the notification-level error (and, for the inline `canUseTool` path that sends no
                    // `_meta`, to the existing/content error) so neither path regresses.
                    const denialReason = status === 'failed' ? extractDenialReason(update._meta) : undefined
                    const errorMessage =
                        update.error?.message ??
                        denialReason ??
                        (status === 'failed' ? notification.error?.message : undefined)
                    const updateContent = Array.isArray(update.content) ? update.content : []

                    if (!existing) {
                        // A reconnect with `?start=latest` can deliver a terminal update whose creating
                        // `tool_call` frame was lost. Upsert a minimal invocation from the update so the
                        // tool card still renders instead of silently vanishing. No completion telemetry
                        // here — without the creation frame there's no reliable start time or tool name.
                        const rawServerName = 'posthog'
                        const rawToolName = String(update.title ?? '')
                        const { resolvedKey, innerToolName, innerInput } = resolveToolKey(
                            rawServerName,
                            rawToolName,
                            rawInput ?? {}
                        )
                        actions.upsertToolInvocation({
                            toolCallId,
                            rawServerName,
                            rawToolName,
                            innerToolName,
                            resolvedKey,
                            input: rawInput ?? {},
                            innerInput,
                            status,
                            title: update.title,
                            locations: update.locations,
                            contentBlocks: updateContent,
                            ...(errorMessage !== undefined ? { error: { message: errorMessage } } : {}),
                        })
                        break
                    }

                    // The tool's args stream in across updates (e.g. an `exec` command or a tool's
                    // input building up), so fold the latest rawInput in and re-resolve the registry
                    // key from it rather than freezing the empty input the initial tool_call carried.
                    const reResolved = rawInput
                        ? resolveToolKey(
                              existing.rawServerName,
                              existing.rawToolName,
                              rawInput,
                              existing.claudeToolName
                          )
                        : undefined
                    actions.updateToolInvocation(toolCallId, {
                        status,
                        title: update.title ?? existing.title,
                        progress: update.progress ?? existing.progress,
                        output: update.rawOutput ?? existing.output,
                        locations: update.locations ?? existing.locations,
                        contentBlocks: [...existing.contentBlocks, ...updateContent],
                        error: errorMessage !== undefined ? { message: errorMessage } : existing.error,
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
                    // transitions to a terminal status. `duration_ms` is measured from the turn start
                    // since per-tool start timing isn't carried on the wire. Suppressed while replaying
                    // history so a reopen doesn't re-count prior-session tool calls; the missing-creation
                    // case is handled above and never reaches here. Report the freshly re-resolved key
                    // (e.g. an `exec`-wrapped inner tool) rather than the stale initial one.
                    if (
                        cache.bootstrapReplay !== true &&
                        (status === 'completed' || status === 'failed') &&
                        existing.status !== 'completed' &&
                        existing.status !== 'failed'
                    ) {
                        const startedAt = cache.turnStartedAtMs as number | undefined
                        posthog.capture('tool_call_completed', {
                            conversation_id: props.conversationId,
                            trace_id: values.traceId,
                            tool_call_id: toolCallId,
                            tool_qualified_name: reResolved?.resolvedKey ?? existing.resolvedKey,
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
    afterMount(({ cache }) => {
        // Mutable dedup-hash store (see `ingestAcpFrame`) — initialized eagerly so it's always a Set.
        cache.ingestedEntryHashes = new Set<string>()
    }),
])
