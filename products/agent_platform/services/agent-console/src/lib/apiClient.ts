/**
 * Typed REST client for the agent console.
 *
 * Paths mirror the real PostHog Django REST surface (see
 * `products/agent_platform/backend/api.py`). The browser hits
 * same-origin `/api/projects/<teamId>/...` which the Next.js
 * catch-all route forwards to Django with the user's OAuth token
 * attached server-side.
 *
 * Every call takes the team id explicitly — callers pull it from
 * `useSessionTeamId()` (sourced from `/api/auth/me`). No module-level
 * project state, so switching teams later doesn't require an app
 * reload.
 *
 * The console is read-mostly. Writes are the agent runner's job: the
 * user asks the concierge dock, the agent POSTs to the same Django
 * endpoints via MCP, the console refetches on its next navigation.
 */

import type { AssistantTurnPart, ChatSession } from '@posthog/agent-chat'
import type {
    AgentApplicationFixture,
    AgentRevisionFixture,
    AgentStats,
    BundleFile,
    BundleFileLanguage,
    FleetStats,
    LogEntry,
} from '@posthog/agent-chat/fixtures'

import type {
    AgentApplicationPreviewTokenResponseApi,
    AgentRevisionCronFireRequestApi,
    AgentRevisionCronFireResponseApi,
    AgentApplicationSessionLogsResponseApi,
    AgentApplicationSessionsListResponseApi,
    AgentApplicationSessionsRetrieveResponseApi,
    AgentApprovalRequestApi,
    AgentApprovalRequestStateEnumApi,
    AgentConversationMessageApi,
    AgentFleetLiveSessionsResponseApi,
    AgentFleetLiveSessionSummaryApi,
    AgentSessionPrincipalApi,
    AgentSessionStateEnumApi,
    AgentSessionSummaryApi,
    LogEntryApi,
} from '@/generated/agent-platform.api.schemas'

function posthogUrl(teamId: number, suffix: string): string {
    return `/api/projects/${teamId}${suffix}`
}

async function getJson<T>(url: string): Promise<T> {
    const res = await fetch(url, { headers: { Accept: 'application/json' } })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as T
}

async function postJson<TBody, TResult>(url: string, body: TBody): Promise<TResult> {
    const res = await fetch(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as TResult
}

async function putJson<TBody, TResult>(url: string, body: TBody): Promise<TResult> {
    const res = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as TResult
}

async function deleteJson<TResult>(url: string): Promise<TResult> {
    const res = await fetch(url, {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as TResult
}

async function safeError(res: Response): Promise<string> {
    try {
        const body = (await res.json()) as { error?: string; detail?: string }
        return body.error ?? body.detail ?? `${res.status} ${res.statusText}`
    } catch {
        return `${res.status} ${res.statusText}`
    }
}

export class ApiError extends Error {
    readonly status: number
    constructor(status: number, message: string) {
        super(message)
        this.status = status
        this.name = 'ApiError'
    }
}

/* ── HogQL (AI observability rollups) ────────────────────────────── */

/** Minimal shape of a `HogQLQuery` response from `/query/`. */
export interface HogqlResult {
    results: unknown[][]
    columns: string[]
}

/**
 * Run a read-only HogQL query against the team's own project. Used by the
 * analytics dashboard to roll up the agents' `$ai_*` observability events
 * (captured into this team's project by the runner). Requires the `query:read`
 * OAuth scope; the same-origin proxy forwards the user's token.
 */
export async function runHogql(teamId: number, query: string): Promise<HogqlResult> {
    const res = await postJson<{ query: { kind: string; query: string } }, Partial<HogqlResult>>(
        posthogUrl(teamId, '/query/'),
        { query: { kind: 'HogQLQuery', query } }
    )
    return { results: res.results ?? [], columns: res.columns ?? [] }
}

/* ── Applications ────────────────────────────────────────────────── */

export async function listAgents(
    teamId: number,
    opts: { includeArchived?: boolean } = {}
): Promise<AgentApplicationFixture[]> {
    const qs = opts.includeArchived ? '?include_archived=true' : ''
    const { results } = await getJson<{ results: AgentApplicationFixture[] }>(
        posthogUrl(teamId, `/agent_applications/${qs}`)
    )
    return results
}

export async function getAgent(teamId: number, slug: string): Promise<AgentApplicationFixture> {
    return getJson<AgentApplicationFixture>(posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/`))
}

/* ── Env / secrets (per-key REST) ────────────────────────────────── */

/**
 * Per-key REST surface for the encrypted env block. The server never
 * returns decrypted values — only key names and set/unset status. The
 * concierge agent uses these in tandem with `buildSecretEditUrl()` so it
 * can either (a) call a client tool that opens the editor, or (b) hand a
 * deep link to the user and react when the same-page callback fires.
 *
 * Mirrors:
 *   GET    /agent_applications/<slug>/env_keys/
 *   GET    /agent_applications/<slug>/env_keys/<KEY>/
 *   PUT    /agent_applications/<slug>/env_keys/<KEY>/
 *   DELETE /agent_applications/<slug>/env_keys/<KEY>/
 */
export interface EnvKeyStatus {
    key: string
    is_set: boolean
}

function envKeysUrl(teamId: number, slug: string, key?: string): string {
    const base = `/agent_applications/${encodeURIComponent(slug)}/env_keys/`
    return posthogUrl(teamId, key ? `${base}${encodeURIComponent(key)}/` : base)
}

export async function listEnvKeys(teamId: number, slug: string): Promise<string[]> {
    const res = await getJson<{ keys: string[] }>(envKeysUrl(teamId, slug))
    return res.keys
}

export async function getEnvKey(teamId: number, slug: string, key: string): Promise<EnvKeyStatus> {
    return getJson<EnvKeyStatus>(envKeysUrl(teamId, slug, key))
}

export async function setEnvKey(teamId: number, slug: string, key: string, value: string): Promise<EnvKeyStatus> {
    return putJson<{ value: string }, EnvKeyStatus>(envKeysUrl(teamId, slug, key), { value })
}

export async function clearEnvKey(teamId: number, slug: string, key: string): Promise<EnvKeyStatus> {
    return deleteJson<EnvKeyStatus>(envKeysUrl(teamId, slug, key))
}

/* ── Revisions ───────────────────────────────────────────────────── */

export async function listRevisions(teamId: number, slug: string): Promise<AgentRevisionFixture[]> {
    const { results } = await getJson<{ results: AgentRevisionFixture[] }>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/revisions/`)
    )
    return results
}

/**
 * Bulk-pull a revision's typed bundle. Django returns the typed shape
 * `{ bundle: { agent_md, skills, tools, spec }, ... }`. We flatten it
 * back to a `BundleFile[]` keyed by canonical S3 path so the existing
 * file-tree UI works unchanged.
 */
interface TypedBundleResponse {
    bundle: {
        agent_md: string
        skills: { id: string; description: string; body: string }[]
        tools: { id: string; description: string; args_schema: Record<string, unknown>; source: string }[]
    }
}

export async function getBundle(teamId: number, slug: string, revisionId: string): Promise<BundleFile[]> {
    const raw = await getJson<TypedBundleResponse>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/bundle/`
        )
    )
    const bundle = raw.bundle ?? { agent_md: '', skills: [], tools: [] }
    const out: BundleFile[] = []
    if (bundle.agent_md !== undefined) {
        out.push({ path: 'agent.md', content: bundle.agent_md, language: languageForPath('agent.md') })
    }
    for (const skill of bundle.skills ?? []) {
        out.push({
            path: `skills/${skill.id}/SKILL.md`,
            content: skill.body,
            language: 'markdown',
        })
    }
    for (const tool of bundle.tools ?? []) {
        const sourcePath = `tools/${tool.id}/source.ts`
        out.push({ path: sourcePath, content: tool.source, language: 'typescript' })
        const schemaPath = `tools/${tool.id}/schema.json`
        const schemaText = JSON.stringify({ description: tool.description, args_schema: tool.args_schema }, null, 2)
        out.push({ path: schemaPath, content: schemaText, language: 'json' })
    }
    out.sort((a, b) => a.path.localeCompare(b.path))
    return out
}

export interface SlackManifestResponse {
    revision_id: string
    /** Slack app manifest (opaque JSON) to paste into the "create from manifest" flow. */
    manifest: Record<string, unknown>
    notes: string[]
    events_url: string | null
    interactivity_url: string | null
}

export async function getSlackManifest(
    teamId: number,
    slug: string,
    revisionId: string
): Promise<SlackManifestResponse> {
    return getJson<SlackManifestResponse>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/slack_manifest/`
        )
    )
}

function languageForPath(path: string): BundleFileLanguage {
    if (path.endsWith('.md') || path.endsWith('.mdx')) {
        return 'markdown'
    }
    // TS/JS share the same highlighter — compiled.js lives next to source.ts
    // in tool bundles, and authors should be able to read both.
    if (path.endsWith('.ts') || path.endsWith('.tsx') || path.endsWith('.js') || path.endsWith('.jsx')) {
        return 'typescript'
    }
    if (path.endsWith('.json')) {
        return 'json'
    }
    return 'text'
}

/* ── Sessions ────────────────────────────────────────────────────── */

/**
 * Wire types come from `@agent-platform/api` (generated by
 * `hogli build:openapi` from the Django serializers). The mappers
 * below take the wire shape and produce the frontend `ChatSession`
 * that `@posthog/agent-chat` consumers expect.
 *
 * If any of these field reads break after a regen, that's the schema
 * drift signal we want — fix the mapper rather than casting through it.
 */

export interface ListSessionsResult {
    sessions: ChatSession[]
    /** Total matching sessions on the server, before pagination. */
    count: number
}

export async function listSessionsForAgent(
    teamId: number,
    slug: string,
    agent: { id: string; name: string; slug: string },
    params: { limit?: number; offset?: number } = {}
): Promise<ListSessionsResult> {
    const qsParams = new URLSearchParams()
    if (params.limit !== undefined) {
        qsParams.set('limit', String(params.limit))
    }
    if (params.offset !== undefined) {
        qsParams.set('offset', String(params.offset))
    }
    const qs = qsParams.toString()
    const { results, count } = await getJson<AgentApplicationSessionsListResponseApi>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/sessions/${qs ? `?${qs}` : ''}`)
    )
    return { sessions: results.map((s) => summaryToChatSession(s, agent)), count }
}

function summaryToChatSession(
    s: AgentSessionSummaryApi,
    agent: { id: string; name: string; slug: string }
): ChatSession {
    return {
        id: s.id,
        application: { id: agent.id, name: agent.name, slug: agent.slug },
        principal: principalToFrontend(s.principal),
        // The list endpoint doesn't return the transcript — surface the
        // preview (last assistant text) as a synthetic assistant turn so
        // the row shows something meaningful. Full transcript is fetched
        // on the per-session detail page.
        turns: s.preview
            ? [
                  {
                      kind: 'assistant',
                      id: `preview:${s.id}`,
                      timestamp: s.updated_at,
                      parts: [{ kind: 'text', text: s.preview }],
                  },
              ]
            : [],
        state: mapSessionState(s.state),
        pendingApprovals: [],
        usage: {
            inputTokens: s.usage_total.tokens_in,
            outputTokens: s.usage_total.tokens_out,
            costUsd: s.usage_total.cost_total,
        },
        started_at: s.created_at,
        ended_at: isTerminalState(s.state) ? s.updated_at : undefined,
        trigger: triggerMetadataToSessionTrigger(s.trigger_metadata),
        triggerKind: triggerKindFromMetadata(s.trigger_metadata),
    }
}

const TRIGGER_KINDS: ReadonlySet<string> = new Set(['chat', 'slack', 'cron', 'webhook', 'mcp'])

/**
 * Coarse trigger source for list display + filtering — reads `kind` off the
 * `trigger_metadata` the ingress/janitor stamps on every session. Distinct
 * from `triggerMetadataToSessionTrigger`, which builds the rich typed shape
 * only where it can be fully reconstructed (cron). Returns undefined for rows
 * predating the `kind` stamp.
 */
function triggerKindFromMetadata(metadata: Record<string, unknown> | null | undefined): ChatSession['triggerKind'] {
    const kind = metadata && typeof metadata === 'object' ? (metadata as { kind?: unknown }).kind : undefined
    return typeof kind === 'string' && TRIGGER_KINDS.has(kind) ? (kind as ChatSession['triggerKind']) : undefined
}

/**
 * Map the raw `trigger_metadata` JSONB the ingress/janitor stamps at enqueue
 * time onto the typed `SessionTrigger` the playback / detail panes consume.
 * Unknown shapes return undefined; the consumer renders a neutral fallback.
 * Cron is the only kind we surface a *rich* typed shape for today; the coarse
 * source label for every kind comes from `triggerKindFromMetadata`.
 */
function triggerMetadataToSessionTrigger(metadata: Record<string, unknown> | null | undefined): ChatSession['trigger'] {
    if (!metadata || typeof metadata !== 'object') {
        return undefined
    }
    const kind = (metadata as { kind?: unknown }).kind
    if (kind !== 'cron') {
        return undefined
    }
    const m = metadata as {
        cron_name?: unknown
        schedule?: unknown
        fired_at?: unknown
        manual?: unknown
        timezone?: unknown
    }
    if (typeof m.cron_name !== 'string' || typeof m.schedule !== 'string' || typeof m.fired_at !== 'string') {
        return undefined
    }
    return {
        kind: 'cron',
        cronName: m.cron_name,
        schedule: m.schedule,
        firedAt: m.fired_at,
        timezone: typeof m.timezone === 'string' ? m.timezone : undefined,
        manual: m.manual === true,
    }
}

/**
 * Per-session detail. Django/janitor returns the raw runtime session
 * shape (snake_case fields, pi-ai `conversation` array); this call
 * maps it into the frontend `ChatSession` shape so playback + stats
 * work without per-component conversion. Pass the parent `agent` so we
 * can populate `application: AgentApplicationRef`.
 */
export async function getSession(
    teamId: number,
    slug: string,
    sessionId: string,
    agent: { id: string; name: string; slug: string }
): Promise<ChatSession> {
    const raw = await getJson<AgentApplicationSessionsRetrieveResponseApi>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/`)
    )
    return detailToChatSession(raw, agent)
}

function detailToChatSession(
    raw: AgentApplicationSessionsRetrieveResponseApi,
    agent: { id: string; name: string; slug: string }
): ChatSession {
    return {
        id: raw.id,
        application: { id: agent.id, name: agent.name, slug: agent.slug },
        principal: principalToFrontend(raw.principal),
        turns: conversationToTurns(raw.conversation, raw.id),
        state: mapSessionState(raw.state),
        pendingApprovals: [],
        usage: {
            inputTokens: raw.usage_total.tokens_in,
            outputTokens: raw.usage_total.tokens_out,
            costUsd: raw.usage_total.cost_total,
        },
        started_at: raw.created_at,
        ended_at: isTerminalState(raw.state) ? raw.updated_at : undefined,
        trigger: triggerMetadataToSessionTrigger(raw.trigger_metadata),
        triggerKind: triggerKindFromMetadata(raw.trigger_metadata),
    }
}

/**
 * Wire principal -> frontend principal. The wire has no `display_name`
 * field; we derive a label from `id` and humanise the `kind` as
 * fallback. `service`/`internal`/`shared_secret` are non-human (the
 * agent ran itself or was triggered by infra); `anonymous`/`slack` are
 * treated as human-driven for display purposes.
 */
function principalToFrontend(p: AgentSessionPrincipalApi | null): ChatSession['principal'] {
    if (!p) {
        return { kind: 'human', displayName: 'unknown' }
    }
    const systemKinds = new Set(['service', 'internal', 'shared_secret'])
    const kind: ChatSession['principal']['kind'] = systemKinds.has(p.kind) ? 'system' : 'human'
    const displayName = p.id ?? humanisePrincipalKind(p.kind)
    return { kind, displayName }
}

function humanisePrincipalKind(kind: AgentSessionPrincipalApi['kind']): string {
    switch (kind) {
        case 'anonymous':
            return 'Anonymous'
        case 'slack':
            return 'Slack'
        case 'service':
            return 'Service'
        case 'internal':
            return 'Internal'
        case 'shared_secret':
            return 'Shared secret'
    }
}

function isTerminalState(s: AgentSessionStateEnumApi): boolean {
    return s === 'completed' || s === 'closed' || s === 'failed' || s === 'cancelled'
}

function mapSessionState(s: AgentSessionStateEnumApi): ChatSession['state'] {
    switch (s) {
        case 'queued':
            return 'idle'
        case 'running':
            return 'streaming'
        case 'completed':
        case 'closed':
            return 'completed'
        case 'cancelled':
            return 'cancelled'
        case 'failed':
            return 'failed'
    }
}

/**
 * Walk the runtime conversation and build frontend Turns. Tool results
 * are attached to the matching tool_call part on the preceding assistant
 * turn so the playback view can render them inline. Stray tool_results
 * (no matching call — shouldn't happen in practice) are dropped.
 *
 * The generated `AgentConversationMessageApi` is a discriminated union
 * on `role`, but `content` is typed as `unknown` / `unknown[]` since
 * pi-ai's parts can't be expressed in OpenAPI cleanly. We narrow at
 * runtime via the local part shapes below.
 */
function conversationToTurns(messages: AgentConversationMessageApi[], sessionId: string): ChatSession['turns'] {
    const turns: ChatSession['turns'] = []
    // Index of every tool_call part by callId, so a later toolResult can
    // attach without an O(n²) walk.
    type ToolCallPart = Extract<AssistantTurnPart, { kind: 'tool_call' }>
    const toolCallIndex = new Map<string, ToolCallPart>()

    for (let i = 0; i < messages.length; i++) {
        const m = messages[i]
        const iso = new Date(m.timestamp).toISOString()
        const id = `${sessionId}:${i}`
        if (m.role === 'user') {
            const text = userMessageText(m.content)
            // Interactive client-tool wake messages get rerouted onto the
            // matching tool_call's result instead of rendering as a bubble.
            const wake = parseClientToolWake(text)
            if (wake) {
                const target = toolCallIndex.get(wake.call_id)
                if (target) {
                    target.fulfillment = 'client'
                    target.result = wake.ok
                        ? { ok: true, body: wake.result ?? null }
                        : { ok: false, error: wake.error || 'client_tool_failed' }
                    continue
                }
            }
            turns.push({ kind: 'user', id, timestamp: iso, text })
            continue
        }
        if (m.role === 'assistant') {
            turns.push({
                kind: 'assistant',
                id,
                timestamp: iso,
                parts: assistantContentToParts(m.content, toolCallIndex),
            })
            continue
        }
        if (m.role === 'toolResult') {
            attachToolResult(m, toolCallIndex)
        }
    }
    return turns
}

/** User content is either a string or an array of TextContent | ImageContent parts. */
function userMessageText(content: unknown): string {
    if (typeof content === 'string') {
        return content
    }
    if (!Array.isArray(content)) {
        return ''
    }
    return content.map((p) => (isTextPart(p) ? p.text : '')).join('')
}

/** Assistant content is an array of text | thinking | toolCall parts. */
function assistantContentToParts(
    content: unknown,
    toolCallIndex: Map<string, Extract<AssistantTurnPart, { kind: 'tool_call' }>>
): AssistantTurnPart[] {
    if (!Array.isArray(content)) {
        return []
    }
    const parts: AssistantTurnPart[] = []
    for (const c of content) {
        if (isTextPart(c)) {
            parts.push({ kind: 'text', text: c.text })
        } else if (isThinkingPart(c)) {
            parts.push({ kind: 'thinking', text: c.thinking })
        } else if (isToolCallPart(c)) {
            const part: Extract<AssistantTurnPart, { kind: 'tool_call' }> = {
                kind: 'tool_call',
                toolId: c.name,
                callId: c.id,
                fulfillment: 'server',
                args: c.arguments,
            }
            toolCallIndex.set(c.id, part)
            parts.push(part)
        }
    }
    return parts
}

function attachToolResult(
    m: Extract<AgentConversationMessageApi, { role: 'toolResult' }>,
    toolCallIndex: Map<string, Extract<AssistantTurnPart, { kind: 'tool_call' }>>
): void {
    const target = toolCallIndex.get(m.toolCallId)
    if (!target) {
        return
    }
    const text = Array.isArray(m.content) ? m.content.map((p) => (isTextPart(p) ? p.text : '')).join('') : ''
    // Interactive client tools persist a synthetic queued envelope. Mark
    // the call as client-fulfilled so the inline form remounts on reload,
    // and leave `result` unset until the wake message lands.
    if (!m.isError && isInteractiveQueuedEnvelopeText(text)) {
        target.fulfillment = 'client'
        return
    }
    target.result = m.isError ? { ok: false, error: text || 'tool error' } : { ok: true, body: text }
}

function isInteractiveQueuedEnvelopeText(text: string): boolean {
    if (!text || text.length > 2000) {
        return false
    }
    try {
        const parsed = JSON.parse(text) as Record<string, unknown>
        return parsed.queued === true && parsed.interactive === true && typeof parsed.call_id === 'string'
    } catch {
        return false
    }
}

interface ClientToolWake {
    call_id: string
    ok: boolean
    result?: unknown
    error?: string
}

function parseClientToolWake(text: string): ClientToolWake | null {
    if (!text || text.length > 100_000) {
        return null
    }
    try {
        const parsed = JSON.parse(text) as Record<string, unknown>
        if (typeof parsed.call_id !== 'string' || typeof parsed.ok !== 'boolean') {
            return null
        }
        return {
            call_id: parsed.call_id,
            ok: parsed.ok,
            result: parsed.result,
            error: typeof parsed.error === 'string' ? parsed.error : undefined,
        }
    } catch {
        return null
    }
}

/* ── Narrowing helpers for `unknown`-typed wire content ───────────── */

function isTextPart(p: unknown): p is { type: 'text'; text: string } {
    return typeof p === 'object' && p !== null && (p as { type?: unknown }).type === 'text'
}

function isThinkingPart(p: unknown): p is { type: 'thinking'; thinking: string } {
    return typeof p === 'object' && p !== null && (p as { type?: unknown }).type === 'thinking'
}

function isToolCallPart(
    p: unknown
): p is { type: 'toolCall'; id: string; name: string; arguments: Record<string, unknown> } {
    return typeof p === 'object' && p !== null && (p as { type?: unknown }).type === 'toolCall'
}

/**
 * Per-session structured logs from ClickHouse. The runner writes to the
 * shared `log_entries` table via KafkaLogSink; this hits Django's
 * `agent_applications_session_logs` action which queries CH with the
 * `log_source = 'agent_session'` tag. Maps the wire row into the
 * frontend `LogEntry` shape (camelCased level + 'service' tag).
 */
export async function listLogsForSession(teamId: number, slug: string, sessionId: string): Promise<LogEntry[]> {
    const { results } = await getJson<AgentApplicationSessionLogsResponseApi>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/sessions/${encodeURIComponent(sessionId)}/logs/`
        )
    )
    return results.map(logEntryFromWire)
}

/**
 * Wire `message` looks like `[<kind>] <event_name> <json?>` — built by
 * the runner's `toWire()` (services/agent-shared/src/runtime/log-sink.ts).
 * Split it apart so the UI can render the event name prominently with
 * a kind badge and expandable structured fields.
 *
 * Examples seen on the wire:
 *   [meta] session_started {"team_id":1,"agent":"...","rev":"..."}
 *   [chat] assistant_text {"text":"Hello!"}
 *   [tool] tool_call {"name":"@posthog/foo","args":{},"id":"toolu_..."}
 *   [event] completed {"turns":1}
 *
 * If parsing fails for any reason, fall back to the raw message.
 */
function logEntryFromWire(row: LogEntryApi): LogEntry {
    const parsed = parseRunnerMessage(row.message)
    return {
        ts: row.timestamp,
        level: mapLogLevel(row.level),
        // The runner is the only producer for log_source='agent_session'.
        // Surface the prefix kind here so the log row's `service` slot
        // shows `meta` / `chat` / `tool` / `event` / `error` instead of
        // a constant "runner".
        service: parsed.kind ?? 'runner',
        message: parsed.event ?? row.message,
        fields: parsed.fields ?? undefined,
    }
}

interface ParsedRunnerMessage {
    /** Bracket prefix: meta | chat | tool | event | error. Null if absent. */
    kind: string | null
    /** Event name following the bracket prefix. Null if absent. */
    event: string | null
    /** Structured payload following the event name. Null if absent or unparseable. */
    fields: Record<string, unknown> | null
}

const RUNNER_MESSAGE = /^\[([^\]]+)\]\s+(\S+)(?:\s+(\{.*\}))?\s*$/

function parseRunnerMessage(message: string): ParsedRunnerMessage {
    const match = RUNNER_MESSAGE.exec(message)
    if (!match) {
        return { kind: null, event: null, fields: null }
    }
    const [, kind, event, jsonStr] = match
    let fields: Record<string, unknown> | null = null
    if (jsonStr) {
        try {
            const parsed = JSON.parse(jsonStr)
            if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) {
                fields = parsed as Record<string, unknown>
            }
        } catch {
            // Malformed JSON — fall through with no fields. The raw
            // message still survives via the fallback in logEntryFromWire.
        }
    }
    return { kind, event, fields }
}

/** ClickHouse upper-cases level on write — coerce back to the frontend's lowercase union. */
function mapLogLevel(level: string): LogEntry['level'] {
    switch (level.toUpperCase()) {
        case 'DEBUG':
            return 'debug'
        case 'WARNING':
        case 'WARN':
            return 'warn'
        case 'ERROR':
            return 'error'
        case 'FATAL':
            return 'fatal'
        case 'INFO':
        default:
            return 'info'
    }
}

/* ── Preview-token (direct-to-ingress chat for non-live revisions) ── */

/**
 * Mint a short-lived JWT for talking to a non-live revision directly
 * via the public ingress URL. The console fetches this when it enters
 * preview-playground mode for a draft, then attaches the token to
 * every ingress call (header for POST/DELETE, `?preview_token=` for
 * `/listen` since `EventSource` can't set headers).
 *
 * Mirror of the Django `preview_token` action; the JWT payload + secret
 * are shared with the legacy `preview-proxy` action so either path
 * authorizes against ingress identically.
 */
export interface PreviewToken {
    token: string
    expiresIn: number
    ingressSlug: string
}

export async function getPreviewToken(teamId: number, slug: string, revisionId: string): Promise<PreviewToken> {
    const res = await getJson<AgentApplicationPreviewTokenResponseApi>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/preview-token/?revision_id=${encodeURIComponent(revisionId)}`
        )
    )
    return {
        token: res.token,
        expiresIn: res.expires_in,
        ingressSlug: res.ingress_slug,
    }
}

/* ── Revision lifecycle (writes) ─────────────────────────────────── */

/**
 * Freeze a draft → ready. Janitor stamps the bundle sha256 and the
 * revision becomes immutable. The draft → ready transition is
 * required before promote.
 */
export async function freezeRevision(teamId: number, slug: string, revisionId: string): Promise<AgentRevisionFixture> {
    return postJson<Record<string, never>, AgentRevisionFixture>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/freeze/`
        ),
        {}
    )
}

/**
 * Promote a ready revision to live. Atomically swaps
 * `application.live_revision_id` and demotes the previous live to
 * archived (per the lifecycle docs).
 */
export async function promoteRevision(teamId: number, slug: string, revisionId: string): Promise<AgentRevisionFixture> {
    return postJson<Record<string, never>, AgentRevisionFixture>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/promote/`
        ),
        {}
    )
}

/** Archive any revision. Live revisions cannot be archived unless
 * another is promoted first — the API enforces that. */
export async function archiveRevision(teamId: number, slug: string, revisionId: string): Promise<AgentRevisionFixture> {
    return postJson<Record<string, never>, AgentRevisionFixture>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/archive/`
        ),
        {}
    )
}

/**
 * Fire one cron trigger out-of-band — the same execution path the scheduler
 * walks, but on demand. Used by the "Run now" control on a cron trigger so an
 * author can test a cron prompt without waiting for its schedule.
 *
 * `cronName` is the cron trigger's `name` in `spec.triggers[]`. `requestId`
 * makes repeat clicks idempotent (the janitor dedupes on
 * `cron-manual:<rev>:<name>:<request_id>`); omit to fire unconditionally.
 */
export async function fireCron(
    teamId: number,
    slug: string,
    revisionId: string,
    cronName: string,
    requestId?: string
): Promise<AgentRevisionCronFireResponseApi> {
    return postJson<AgentRevisionCronFireRequestApi, AgentRevisionCronFireResponseApi>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/revisions/${encodeURIComponent(revisionId)}/cron/fire/`
        ),
        { cron_name: cronName, ...(requestId ? { request_id: requestId } : {}) }
    )
}

/* ── Fleet / agent rollups (Phase C) ───────────────────────────────── */

/**
 * Shape the janitor returns from `/sessions/stats` and `/fleet/stats`, surfaced
 * unchanged through Django. Kept here (vs in `@posthog/agent-chat`) because
 * agent-chat's `AgentStats` / `FleetStats` are consumer-facing types — the
 * window is implied (24h) and the field names match the UI labels.
 */
interface AggregateStatsWire {
    liveCount: number
    sessionsInWindowCount: number
    spendInWindowUsd: number
    lastActivityAt: string | null
    failedInWindowCount: number
    pendingApprovalsCount: number
}

export async function getAgentStats(teamId: number, slug: string): Promise<AgentStats> {
    const wire = await getJson<AggregateStatsWire>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/stats/`)
    )
    return {
        liveCount: wire.liveCount,
        sessions24hCount: wire.sessionsInWindowCount,
        spend24hUsd: wire.spendInWindowUsd,
        lastActivityAt: wire.lastActivityAt ?? undefined,
        failureRate24h:
            wire.sessionsInWindowCount > 0 ? wire.failedInWindowCount / wire.sessionsInWindowCount : undefined,
    }
}

export async function getFleetStats(teamId: number): Promise<FleetStats> {
    const wire = await getJson<AggregateStatsWire>(posthogUrl(teamId, `/agent_fleet/stats/`))
    return {
        liveSessionCount: wire.liveCount,
        sessions24hCount: wire.sessionsInWindowCount,
        spend24hUsd: wire.spendInWindowUsd,
        approvalsPendingCount: wire.pendingApprovalsCount,
    }
}

/**
 * Fleet-wide live sessions. The wire shape carries `application_id`
 * (UUID) only — no slug / name — so callers must supply an `agentsById`
 * lookup built from the agents list to enrich each row into a proper
 * `ChatSession` with `application: { id, slug, name }`. Sessions whose
 * `application_id` isn't in the lookup (e.g. agent archived between
 * fetches) are dropped — the alternative is rendering "unknown" rows
 * that the rest of the UI can't navigate to.
 */
export async function listLiveSessions(
    teamId: number,
    agentsById: ReadonlyMap<string, { id: string; name: string; slug: string }>
): Promise<ChatSession[]> {
    const { results } = await getJson<AgentFleetLiveSessionsResponseApi>(
        posthogUrl(teamId, `/agent_fleet/live_sessions/`)
    )
    const sessions: ChatSession[] = []
    for (const s of results) {
        const agent = agentsById.get(s.application_id)
        if (!agent) {
            continue
        }
        sessions.push(fleetSummaryToChatSession(s, agent))
    }
    return sessions
}

function fleetSummaryToChatSession(
    s: AgentFleetLiveSessionSummaryApi,
    agent: { id: string; name: string; slug: string }
): ChatSession {
    return {
        id: s.id,
        application: { id: agent.id, name: agent.name, slug: agent.slug },
        principal: principalToFrontend(s.principal),
        // The fleet summary doesn't carry the full transcript — surface
        // the last assistant text (`preview`) as a synthetic turn so the
        // LiveNowPanel row shows something meaningful.
        turns: s.preview
            ? [
                  {
                      kind: 'assistant',
                      id: `preview:${s.id}`,
                      timestamp: s.updated_at,
                      parts: [{ kind: 'text', text: s.preview }],
                  },
              ]
            : [],
        state: mapSessionState(s.state),
        pendingApprovals: [],
        usage: {
            inputTokens: s.usage_total.tokens_in,
            outputTokens: s.usage_total.tokens_out,
            costUsd: s.usage_total.cost_total,
        },
        started_at: s.created_at,
        ended_at: isTerminalState(s.state) ? s.updated_at : undefined,
    }
}

/* ── AI gateway (billing read plane) ─────────────────────────────── */

/**
 * Wire shape of GET /api/projects/<team>/ai_gateway/wallet/. Mirrors
 * the ai-gateway billing service's /v1/wallet response. Hand-rolled
 * here pending the next `hogli build:openapi` regen — swap the local
 * types for the generated ones in one place when that's safe to run.
 *
 * Decimal fields are strings to preserve ledger precision; parse with
 * Number() at the call site (UI rounding is fine for display).
 */
export interface AIGatewayAccount {
    profile: 'A' | 'B' | 'C'
    overage_allowance_usd: string
    period: string
    period_anchor: string
    rate_card_id?: string | null
}

export interface AIGatewayKillSwitch {
    tripped: boolean
    threshold_usd?: string | null
    tripped_at?: string | null
}

export interface AIGatewayWallet {
    team_id: number
    available_usd: string
    pending_usd: string
    balance_usd: string
    spendable_usd: string
    currency: string
    account: AIGatewayAccount
    rolling_hour_usd?: string | null
    kill_switch: AIGatewayKillSwitch
}

export type AIGatewayTransactionType = 'debit' | 'topup' | 'refund' | 'adjustment'

export interface AIGatewayLedgerEntry {
    id: string
    transaction_type: AIGatewayTransactionType
    source: string
    destination: string
    amount_usd: string
    list_cost_usd?: string | null
    reference_id?: string | null
    model?: string | null
    provider?: string | null
    input_tokens?: number | null
    output_tokens?: number | null
    distinct_id?: string | null
    created_at: string
}

export interface AIGatewayLedgerListResponse {
    results: AIGatewayLedgerEntry[]
    next_cursor?: string | null
}

export interface AIGatewayLedgerListOpts {
    limit?: number
    cursor?: string
    transactionType?: AIGatewayTransactionType
    /** Filter to entries whose reference_id starts with this prefix. Use
     * `agent:<session_id>:` to scope to one session. */
    referenceIdPrefix?: string
}

// The agent ai_gateway API was dropped for v0 (see the master catch-up merge on
// ass), so /ai_gateway/wallet/ + /ai_gateway/ledger/ no longer exist server-side.
// Mock both so the billing UI renders empty instead of erroring; rewire to the
// real endpoints when the gateway billing read plane ships again.
export async function getWallet(teamId: number): Promise<AIGatewayWallet> {
    return {
        team_id: teamId,
        available_usd: '0',
        pending_usd: '0',
        balance_usd: '0',
        spendable_usd: '0',
        currency: 'USD',
        account: { profile: 'A', overage_allowance_usd: '0', period: 'monthly', period_anchor: '' },
        rolling_hour_usd: null,
        kill_switch: { tripped: false, threshold_usd: null, tripped_at: null },
    }
}

export async function listLedger(
    _teamId: number,
    _opts: AIGatewayLedgerListOpts = {}
): Promise<AIGatewayLedgerListResponse> {
    return { results: [], next_cursor: null }
}

/* ── Memory ──────────────────────────────────────────────────────── */

export interface MemoryHeader {
    path: string
    description: string
    tags: string[]
    created_at: string | null
    updated_at: string | null
}

export interface MemoryFile extends MemoryHeader {
    content: string
}

export interface MemoryTreeNode {
    name: string
    type: 'folder' | 'file'
    path?: string
    description?: string
    tags?: string[]
    children?: MemoryTreeNode[]
}

export interface MemorySearchResult {
    path: string
    description: string
    tags: string[]
    score: number
    snippet?: string | null
}

function memoryUrl(teamId: number, slug: string, suffix: string): string {
    return posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/memory${suffix}`)
}

export async function listMemoryFiles(
    teamId: number,
    slug: string,
    opts: { prefix?: string } = {}
): Promise<{ count: number; entries: MemoryHeader[] }> {
    const qs = opts.prefix ? `?prefix=${encodeURIComponent(opts.prefix)}` : ''
    return getJson(memoryUrl(teamId, slug, `/files/${qs}`))
}

export async function getMemoryTree(teamId: number, slug: string): Promise<{ root: MemoryTreeNode }> {
    return getJson(memoryUrl(teamId, slug, `/tree/`))
}

export async function readMemoryFile(teamId: number, slug: string, path: string): Promise<MemoryFile> {
    return getJson(memoryUrl(teamId, slug, `/files/by_path/?path=${encodeURIComponent(path)}`))
}

/* ── Tabular reference (the @posthog/table-* JSONL tables) ─────────── */

export interface AgentTableHeader {
    name: string
    size: number
}

export interface AgentTableRows {
    name: string
    total: number
    returned: number
    limit: number
    rows: Record<string, unknown>[]
}

export async function listTables(teamId: number, slug: string): Promise<{ count: number; tables: AgentTableHeader[] }> {
    return getJson(memoryUrl(teamId, slug, `/tables/`))
}

export async function readTable(
    teamId: number,
    slug: string,
    name: string,
    opts: { limit?: number } = {}
): Promise<AgentTableRows> {
    const qs = opts.limit ? `?limit=${opts.limit}` : ''
    return getJson(memoryUrl(teamId, slug, `/tables/${encodeURIComponent(name)}/${qs}`))
}

export async function searchMemoryApi(
    teamId: number,
    slug: string,
    cue: string,
    opts: { prefix?: string; limit?: number } = {}
): Promise<{ cue: string; count: number; results: MemorySearchResult[] }> {
    const qs = new URLSearchParams({ q: cue })
    if (opts.prefix) {
        qs.set('prefix', opts.prefix)
    }
    if (opts.limit !== undefined) {
        qs.set('limit', String(opts.limit))
    }
    return getJson(memoryUrl(teamId, slug, `/search/?${qs}`))
}

export async function createMemoryFile(
    teamId: number,
    slug: string,
    body: { path: string; description: string; content: string; tags?: string[] }
): Promise<MemoryFile> {
    return postJson<typeof body, MemoryFile>(memoryUrl(teamId, slug, `/files/`), body)
}

export async function updateMemoryFile(
    teamId: number,
    slug: string,
    path: string,
    body: { description?: string; content?: string; tags?: string[] }
): Promise<MemoryFile> {
    const res = await fetch(memoryUrl(teamId, slug, `/files/by_path/?path=${encodeURIComponent(path)}`), {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json', Accept: 'application/json' },
        body: JSON.stringify(body),
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
    return (await res.json()) as MemoryFile
}

export async function deleteMemoryFile(teamId: number, slug: string, path: string): Promise<void> {
    const res = await fetch(memoryUrl(teamId, slug, `/files/by_path/?path=${encodeURIComponent(path)}`), {
        method: 'DELETE',
        headers: { Accept: 'application/json' },
    })
    if (!res.ok) {
        throw new ApiError(res.status, await safeError(res))
    }
}

/* ── Native tools catalog ─────────────────────────────────────────── */

/** Mirror of `NativeToolCatalogEntry` on the runner side. `schema.args`
 *  and `schema.returns` are TypeBox schemas — opaque JSON to this client. */
export interface NativeToolCatalogEntry {
    id: string
    schema: {
        description: string
        args: unknown
        returns: unknown
        requires: {
            integrations: string[]
            scopes: string[]
        }
        cost_hint: 'cheap' | 'medium' | 'expensive'
    }
}

export async function listNativeTools(teamId: number): Promise<NativeToolCatalogEntry[]> {
    const res = await getJson<{ tools: NativeToolCatalogEntry[] }>(posthogUrl(teamId, '/agent_native_tools/'))
    return res.tools
}

/* ── Approvals ────────────────────────────────────────────────────── */

/**
 * Wire shape of an `agent_tool_approval_request` row as the Django API surfaces it.
 * Re-exported from the generated type so callers don't reach into `@/generated`.
 */
export type ApprovalRequest = AgentApprovalRequestApi
export type ApprovalState = AgentApprovalRequestStateEnumApi

export interface ListApprovalsOpts {
    /** Single state or comma-separated. Defaults to all states on the wire. */
    state?: ApprovalState | ApprovalState[]
    /** Narrow to one agent — UUID, not slug. */
    agentId?: string
    limit?: number
    offset?: number
}

function approvalsQueryString(opts: ListApprovalsOpts): string {
    const params = new URLSearchParams()
    if (opts.state) {
        const value = Array.isArray(opts.state) ? opts.state.join(',') : opts.state
        params.set('state', value)
    }
    if (opts.agentId) {
        params.set('agent_id', opts.agentId)
    }
    if (opts.limit != null) {
        params.set('limit', String(opts.limit))
    }
    if (opts.offset != null) {
        params.set('offset', String(opts.offset))
    }
    const qs = params.toString()
    return qs ? `?${qs}` : ''
}

/** Fleet-wide listing — drives the `/approvals` screen. Admin-only on the server. */
export async function listFleetApprovals(teamId: number, opts: ListApprovalsOpts = {}): Promise<ApprovalRequest[]> {
    const { results } = await getJson<{ results: ApprovalRequest[] }>(
        posthogUrl(teamId, `/agent_fleet/approvals/${approvalsQueryString(opts)}`)
    )
    return results
}

/** Per-agent listing — drives the `/agents/<slug>/approvals` tab. Admin-only on the server. */
export async function listAgentApprovals(
    teamId: number,
    slug: string,
    opts: Omit<ListApprovalsOpts, 'agentId'> = {}
): Promise<ApprovalRequest[]> {
    const { results } = await getJson<{ results: ApprovalRequest[] }>(
        posthogUrl(teamId, `/agent_applications/${encodeURIComponent(slug)}/approvals/${approvalsQueryString(opts)}`)
    )
    return results
}

/** Single-approval detail — full proposed args, assistant snapshot, decision metadata. */
export async function getApproval(teamId: number, slug: string, approvalId: string): Promise<ApprovalRequest> {
    return getJson<ApprovalRequest>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/approvals/${encodeURIComponent(approvalId)}/`
        )
    )
}

export interface DecideApprovalInput {
    decision: 'approve' | 'reject'
    /** Reason text — surfaced to the model in the synthetic reject result and audit log. */
    reason?: string
    /** Edited args. Server 422s when `approver_scope.allow_edit` is false. */
    edited_args?: Record<string, unknown>
}

export interface DecideApprovalResponse {
    ok: boolean
    state: 'approving' | 'rejected'
}

/** Decide a queued approval. Janitor flips the row + writes the wake marker. */
export async function decideApproval(
    teamId: number,
    slug: string,
    approvalId: string,
    body: DecideApprovalInput
): Promise<DecideApprovalResponse> {
    return postJson<DecideApprovalInput, DecideApprovalResponse>(
        posthogUrl(
            teamId,
            `/agent_applications/${encodeURIComponent(slug)}/approvals/${encodeURIComponent(approvalId)}/decide/`
        ),
        body
    )
}
