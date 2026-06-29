/**
 * AnalyticsSink — the runner's LLM-analytics out-bound. One `$ai_generation`
 * per pi-ai call, one `$ai_span` per tool dispatch, captured through the
 * standard PostHog ingestion path:
 *
 *   runner ──posthog-node──▶ /capture ──ingestion──▶ clickhouse_ai_events_json ──▶ ai_events (CH)
 *
 * Hitting `/capture` (rather than producing into a dedicated Kafka topic)
 * means agent traffic shows up in LLM Analytics with zero new
 * infrastructure — same path the ai-gateway uses for its own observability
 * events.
 *
 * Sinks:
 *   - InMemoryAnalyticsSink (tests + local dev assertions)
 *   - NoopAnalyticsSink (dev/local without a PostHog destination)
 *   - CaptureAnalyticsSink (prod) — thin wrapper over posthog-node.
 *
 * Future "platform-originated == free billing" handling: every event carries
 * `$ai_origin: 'agent_platform_runner'`. The plan is to extend that into a
 * **signed marker** (HMAC over event fields with a platform secret) so a
 * downstream billing filter can verify the marker before excluding the event
 * from billable usage — a plain property is forgeable by anyone with the
 * project key. See `platform-llm-analytics.md` §"Future signed origin
 * marker". Not implemented yet; the unsigned marker is the placeholder.
 */

import { PostHog } from 'posthog-node'

import { createLogger } from './logger'

/**
 * Marker stamped on every event the runner produces. Future signed variant
 * (see module docstring) will replace this with `$ai_origin_signature` —
 * the unsigned form here is a forgeable placeholder, fine for observability
 * but not for billing decisions until the signing work lands.
 */
export const PLATFORM_ORIGIN = 'agent_platform_runner'

/* -------------------------------------------------------------------------- */
/* Event shape — what the runner emits                                        */
/* -------------------------------------------------------------------------- */

interface AnalyticsEventBase {
    /** ISO-8601 (UTC) timestamp. */
    ts: string
    team_id: number
    application_id: string
    revision_id: string
    /** AgentSession UUID — also used as `$ai_trace_id` so all turns of a session share a trace. */
    session_id: string
    /** 1-indexed turn number within the session. */
    turn: number
    /** Stable id for this span. `<session>:<turn>` for generations; spans append `:<tool_call_id>`. */
    span_id: string
    /** Optional parent span — set on tool spans to point at the generation that emitted the toolCall. */
    parent_span_id?: string
    /** Composite — `<principal.kind>:<principal.id>` when known, else `agent:<application_id>`. */
    distinct_id: string
    /** `true` when the entry represents a failure. */
    is_error?: boolean
    /** Free-form failure detail; only set when `is_error` is true. */
    error?: string
}

export interface AnalyticsGenerationEvent extends AnalyticsEventBase {
    kind: 'generation'
    /** pi-ai resolved model id (e.g. `claude-haiku-4-5`). */
    model: string
    /** pi-ai provider name (`anthropic`, `openai`, `posthog-ai-gateway`, …). */
    provider: string
    /** Serialised user/assistant/tool message history sent into the model. */
    input: unknown[]
    /** Serialised assistant message content blocks returned by the model. */
    output: unknown
    input_tokens: number
    output_tokens: number
    cache_read_tokens?: number
    cache_write_tokens?: number
    total_tokens?: number
    /** Wall-clock duration of the pi-ai call, milliseconds. */
    latency_ms: number
    /**
     * Total cost in USD. No longer set by the runner — the gateway emits cost on
     * the gateway path, and ingestion prices direct-path events from the
     * catalog. pi-ai's estimate is never used. Kept on the shape for consumers.
     */
    cost_usd?: number
    /** pi-ai stopReason — `stop`, `length`, `toolUse`, `error`, `aborted`. */
    stop_reason?: string
    /** 0-based index of the model in the policy list that answered. >0 means a fallback. */
    model_attempt?: number
    /** Model id we fell back FROM (the primary that failed), when a fallback happened. */
    fallback_from?: string
}

export interface AnalyticsSpanEvent extends AnalyticsEventBase {
    kind: 'span'
    /** Tool id as declared in `spec.tools` (e.g. `@posthog/query` or a custom id). */
    tool_name: string
    /** pi-ai toolCall id from the generation that produced this span. */
    tool_call_id: string
    /** Arguments after nonce substitution. Never contains plaintext secrets. */
    input: Record<string, unknown>
    /** Tool result content (text/JSON). Truncated upstream when large. */
    output: unknown
    /** Wall-clock duration of the dispatcher's tool execution, milliseconds. */
    latency_ms: number
}

/**
 * One `$ai_trace` per session, emitted at terminal outcome. Gives the LLM
 * Analytics trace list a friendly name + input/output state instead of a bare
 * session UUID — the generations + spans already group under the same
 * `$ai_trace_id`. Best-effort, like the other events.
 */
export interface AnalyticsTraceEvent extends AnalyticsEventBase {
    kind: 'trace'
    /** Friendly trace name — the agent's display name (`name` then `slug`). */
    trace_name: string
    /** The input that opened the session (first user message / cron prompt). */
    input_state: unknown
    /** The final assistant output at session end. */
    output_state: unknown
}

export type AnalyticsEvent = AnalyticsGenerationEvent | AnalyticsSpanEvent | AnalyticsTraceEvent

export interface AnalyticsSink {
    write(events: AnalyticsEvent[]): Promise<void>
}

/* -------------------------------------------------------------------------- */
/* Helpers                                                                    */
/* -------------------------------------------------------------------------- */

/**
 * Compose a stable `distinct_id` for analytics emission. When the session
 * has a known principal (`pat`, `slack`, `internal`, …) we use
 * `<kind>:<id>` so Insights / LLM Analytics can slice per-user. For
 * anonymous public-agent sessions we fall back to `agent:<application_id>`
 * so events still bucket cleanly per agent.
 */
export function analyticsDistinctId(session: {
    application_id: string
    principal: { kind: string; id?: string } | null
}): string {
    if (session.principal && session.principal.id) {
        return `${session.principal.kind}:${session.principal.id}`
    }
    return `agent:${session.application_id}`
}

/** Stable span id for a model generation. Used as parent for tool spans in the same turn. */
export function generationSpanId(sessionId: string, turn: number): string {
    return `${sessionId}:gen:${turn}`
}

/** Stable span id for a tool dispatch. Pairs to its parent generation via `parent_span_id`. */
export function toolSpanId(sessionId: string, turn: number, toolCallId: string): string {
    return `${sessionId}:tool:${turn}:${toolCallId}`
}

/**
 * Build the `$ai_*` property bag PostHog's LLM Analytics surface keys on.
 * Names match the existing `ai_events` MV schema
 * (`posthog/models/ai_events/sql.py:HEAVY_AI_PROPERTIES`) and what the
 * `ai-gateway` PostHogCallback emits. Exposed for tests + the future
 * signed-origin work.
 */
export function buildAnalyticsProperties(event: AnalyticsEvent): Record<string, unknown> {
    const base: Record<string, unknown> = {
        $ai_trace_id: event.session_id,
        $ai_span_id: event.span_id,
        $agent_application_id: event.application_id,
        $agent_revision_id: event.revision_id,
        $agent_session_id: event.session_id,
        $agent_turn: event.turn,
        // Marker for the future "platform-originated = free" billing filter.
        // Today this is an unsigned property — forgeable by anyone with the
        // project key. The intended evolution is a signed variant
        // (`$ai_origin_signature`) so the billing filter can verify before
        // excluding from billable usage. See module docstring + plan.
        $ai_origin: PLATFORM_ORIGIN,
        // team_id is stamped explicitly so a per-team filter / billing rollup
        // doesn't need to resolve through the project-key→team mapping.
        team_id: event.team_id,
    }
    if (event.parent_span_id) {
        base.$ai_parent_id = event.parent_span_id
    }
    if (event.is_error) {
        base.$ai_is_error = true
        if (event.error) {
            base.$ai_error = event.error
        }
    }
    if (event.kind === 'generation') {
        base.$ai_model = event.model
        base.$ai_provider = event.provider
        base.$ai_input = event.input
        base.$ai_output_choices = event.output
        base.$ai_input_tokens = event.input_tokens
        base.$ai_output_tokens = event.output_tokens
        if (event.cache_read_tokens !== undefined) {
            base.$ai_cache_read_input_tokens = event.cache_read_tokens
        }
        if (event.cache_write_tokens !== undefined) {
            base.$ai_cache_creation_input_tokens = event.cache_write_tokens
        }
        if (event.total_tokens !== undefined) {
            base.$ai_total_tokens = event.total_tokens
        }
        base.$ai_latency = event.latency_ms / 1000
        if (event.cost_usd !== undefined) {
            base.$ai_total_cost_usd = event.cost_usd
        }
        if (event.stop_reason) {
            base.$ai_stop_reason = event.stop_reason
        }
        if (event.model_attempt !== undefined) {
            base.$agent_model_attempt = event.model_attempt
        }
        if (event.fallback_from) {
            base.$ai_fallback_from = event.fallback_from
        }
    } else if (event.kind === 'span') {
        base.$ai_span_name = event.tool_name
        base.$ai_tool_call_id = event.tool_call_id
        base.$ai_input_state = event.input
        base.$ai_output_state = event.output
        base.$ai_latency = event.latency_ms / 1000
    } else {
        // $ai_trace — the trace-level summary the LLM Analytics list keys on.
        base.$ai_span_name = event.trace_name
        base.$ai_input_state = event.input_state
        base.$ai_output_state = event.output_state
    }
    return base
}

export function eventNameFor(event: AnalyticsEvent): '$ai_generation' | '$ai_span' | '$ai_trace' {
    if (event.kind === 'generation') {
        return '$ai_generation'
    }
    return event.kind === 'span' ? '$ai_span' : '$ai_trace'
}

/* -------------------------------------------------------------------------- */
/* Noop sink — dev fallback when no PostHog destination is configured.        */
/* -------------------------------------------------------------------------- */

/**
 * Drops every event on the floor. Wired in dev / local when the runner has no
 * `POSTHOG_ANALYTICS_API_KEY` to talk to. Prod and the test harness use
 * `CaptureAnalyticsSink` against a real PostHog endpoint; there is no
 * in-memory test variant — assertions on analytics go through the sink's
 * `tap` option below, the same way `KafkaLogSink` exposes wire payloads.
 */
export class NoopAnalyticsSink implements AnalyticsSink {
    async write(_events: AnalyticsEvent[]): Promise<void> {
        // intentionally empty
    }
}

/* -------------------------------------------------------------------------- */
/* Capture sink — production path. Goes through standard PostHog ingestion.   */
/* -------------------------------------------------------------------------- */

export interface CaptureAnalyticsSinkOptions {
    /** PostHog project API key. Same kind of key `posthog-node` takes. */
    apiKey: string
    /** Defaults to `https://us.posthog.com`. Set this to your region or self-hosted URL. */
    host?: string
    /** Optional batching tuning; defaults match `posthog-node`'s out-of-box behaviour. */
    flushAt?: number
    flushInterval?: number
    /** Optional logger for capture failures. Defaults to the agent-shared pino. */
    logger?: {
        info: (msg: string, meta?: unknown) => void
        warn: (msg: string, meta?: unknown) => void
        error: (msg: string, meta?: unknown) => void
    }
}

/**
 * Production capture sink. One `posthog-node` PostHog client per runner
 * process; events batch + flush via the SDK. `shutdown()` drains the
 * pending buffer — wire it into the runner's SIGTERM handler so events
 * don't get dropped on rolling deploys.
 */
export class CaptureAnalyticsSink implements AnalyticsSink {
    private readonly opts: CaptureAnalyticsSinkOptions
    private readonly log: NonNullable<CaptureAnalyticsSinkOptions['logger']>
    private client: PostHog | null = null
    private connectPromise: Promise<void> | null = null

    constructor(opts: CaptureAnalyticsSinkOptions) {
        this.opts = opts
        if (opts.logger) {
            this.log = opts.logger
        } else {
            const pino = createLogger('analytics-capture')
            this.log = {
                info: (m, meta) => pino.info(meta ?? {}, m),
                warn: (m, meta) => pino.warn(meta ?? {}, m),
                error: (m, meta) => pino.error(meta ?? {}, m),
            }
        }
    }

    async connect(): Promise<void> {
        if (this.client) {
            return
        }
        if (!this.connectPromise) {
            this.connectPromise = this.doConnect()
        }
        return this.connectPromise
    }

    private async doConnect(): Promise<void> {
        this.client = new PostHog(this.opts.apiKey, {
            host: this.opts.host,
            flushAt: this.opts.flushAt ?? 20,
            flushInterval: this.opts.flushInterval ?? 10_000,
        })
        this.log.info('capture analytics sink connected', { host: this.opts.host ?? 'default' })
    }

    async write(events: AnalyticsEvent[]): Promise<void> {
        if (!this.client) {
            this.log.warn('dropping analytics events (not connected)', { count: events.length })
            return
        }
        for (const event of events) {
            try {
                this.client.capture({
                    distinctId: event.distinct_id,
                    event: eventNameFor(event),
                    properties: buildAnalyticsProperties(event),
                    groups: { project: String(event.team_id) },
                    timestamp: new Date(event.ts),
                })
            } catch (err) {
                this.log.error('capture failed', { event: eventNameFor(event), error: String(err) })
            }
        }
    }

    /**
     * Drains the SDK's pending buffer + shuts down. Production wires this
     * into the SIGTERM handler so a rolling deploy doesn't drop the last
     * batch.
     */
    async shutdown(): Promise<void> {
        if (!this.client) {
            return
        }
        try {
            await this.client.shutdown()
        } catch (err) {
            this.log.error('capture shutdown failed', { error: String(err) })
        }
        this.client = null
    }
}

/* -------------------------------------------------------------------------- */
/* Routing capture sink — per-team destination (the native, zero-config path). */
/* -------------------------------------------------------------------------- */

/**
 * Minimal `posthog-node` surface the routing sink needs. Lets tests inject a
 * stub instead of a real client (no network, deterministic assertions).
 */
export interface PostHogLike {
    capture(payload: {
        distinctId: string
        event: string
        properties?: Record<string, unknown>
        timestamp?: Date
    }): void
    shutdown(): Promise<void>
}

type AnalyticsLogger = NonNullable<CaptureAnalyticsSinkOptions['logger']>

export interface RoutingAnalyticsSinkOptions {
    /**
     * Resolve a team's destination project key (`phc_…`). The runner wires
     * `PgTeamApiKeyResolver.resolve` here so each agent's events land in its
     * own team's project — native LLM Analytics with zero per-agent config.
     * Return `null` (or throw) to fall back to `fallbackApiKey`.
     */
    resolveApiKey: (teamId: number) => Promise<string | null>
    /**
     * Destination when `resolveApiKey` yields nothing (team has no api_token,
     * resolver error). Unset → such events are dropped (warned, never thrown —
     * analytics is best-effort). Wire `POSTHOG_ANALYTICS_API_KEY` here.
     */
    fallbackApiKey?: string
    host?: string
    flushAt?: number
    flushInterval?: number
    /**
     * Cap on distinct destination clients kept alive at once. A runner serving
     * many teams would otherwise accumulate one `posthog-node` client per team;
     * past this we LRU-evict (and drain) the least-recently-used. Default 64.
     */
    maxClients?: number
    /** Test seam — build a client for a key. Defaults to real `posthog-node`. */
    createClient?: (apiKey: string, opts: { host?: string; flushAt?: number; flushInterval?: number }) => PostHogLike
    /** Test seam — fired for every event before capture with the resolved key (`null` = dropped). */
    tap?: (entry: {
        apiKey: string | null
        eventName: string
        event: AnalyticsEvent
        properties: Record<string, unknown>
    }) => void
    logger?: AnalyticsLogger
}

const DEFAULT_MAX_CLIENTS = 64

/**
 * Production analytics sink. Resolves each event's destination project key from
 * its `team_id` and captures into that team's own PostHog project, so agent
 * traffic shows up natively in the owning team's LLM Analytics. Holds a bounded
 * LRU of `posthog-node` clients (one per distinct key); `shutdown()` drains all.
 *
 * Best-effort throughout: resolver errors and capture failures are logged, not
 * thrown — analytics must never break a session.
 */
export class RoutingAnalyticsSink implements AnalyticsSink {
    private readonly opts: RoutingAnalyticsSinkOptions
    private readonly log: AnalyticsLogger
    private readonly maxClients: number
    private readonly createClient: NonNullable<RoutingAnalyticsSinkOptions['createClient']>
    /** Insertion-ordered → front is least-recently-used. Re-inserted on access. */
    private readonly clients = new Map<string, PostHogLike>()

    constructor(opts: RoutingAnalyticsSinkOptions) {
        this.opts = opts
        this.maxClients = opts.maxClients ?? DEFAULT_MAX_CLIENTS
        this.createClient =
            opts.createClient ??
            ((apiKey, clientOpts) =>
                new PostHog(apiKey, {
                    host: clientOpts.host,
                    flushAt: clientOpts.flushAt ?? 20,
                    flushInterval: clientOpts.flushInterval ?? 10_000,
                }))
        if (opts.logger) {
            this.log = opts.logger
        } else {
            const pino = createLogger('analytics-routing')
            this.log = {
                info: (m, meta) => pino.info(meta ?? {}, m),
                warn: (m, meta) => pino.warn(meta ?? {}, m),
                error: (m, meta) => pino.error(meta ?? {}, m),
            }
        }
    }

    async write(events: AnalyticsEvent[]): Promise<void> {
        if (events.length === 0) {
            return
        }
        // Resolve one key per distinct team in the batch (the resolver caches,
        // but de-duping here avoids redundant awaits when a turn emits several).
        const keyByTeam = new Map<number, string | null>()
        for (const teamId of new Set(events.map((e) => e.team_id))) {
            keyByTeam.set(teamId, await this.resolveTeamKey(teamId))
        }

        let dropped = 0
        for (const event of events) {
            const resolved = keyByTeam.get(event.team_id) ?? null
            const apiKey = resolved ?? this.opts.fallbackApiKey ?? null
            const eventName = eventNameFor(event)
            const properties = buildAnalyticsProperties(event)
            this.opts.tap?.({ apiKey, eventName, event, properties })
            if (!apiKey) {
                dropped++
                continue
            }
            try {
                this.clientFor(apiKey).capture({
                    distinctId: event.distinct_id,
                    event: eventName,
                    properties,
                    timestamp: new Date(event.ts),
                })
            } catch (err) {
                this.log.error('capture failed', { event: eventName, error: String(err) })
            }
        }
        if (dropped > 0) {
            this.log.warn('dropped analytics events (no destination key)', { count: dropped })
        }
    }

    private async resolveTeamKey(teamId: number): Promise<string | null> {
        try {
            return await this.opts.resolveApiKey(teamId)
        } catch (err) {
            this.log.warn('resolve destination key failed', { team_id: teamId, error: String(err) })
            return null
        }
    }

    /** Get-or-create the client for a key, refreshing its LRU recency. */
    private clientFor(apiKey: string): PostHogLike {
        const existing = this.clients.get(apiKey)
        if (existing) {
            // Re-insert so it moves to the most-recently-used end.
            this.clients.delete(apiKey)
            this.clients.set(apiKey, existing)
            return existing
        }
        const client = this.createClient(apiKey, {
            host: this.opts.host,
            flushAt: this.opts.flushAt,
            flushInterval: this.opts.flushInterval,
        })
        this.clients.set(apiKey, client)
        this.evictIfNeeded()
        return client
    }

    private evictIfNeeded(): void {
        while (this.clients.size > this.maxClients) {
            const oldestKey = this.clients.keys().next().value
            if (oldestKey === undefined) {
                return
            }
            const victim = this.clients.get(oldestKey)
            this.clients.delete(oldestKey)
            // Drain in the background so a slow flush doesn't block the hot path.
            victim?.shutdown().catch((err) => this.log.error('evicted client shutdown failed', { error: String(err) }))
        }
    }

    /** Drains every live client. Wire into the runner's SIGTERM handler. */
    async shutdown(): Promise<void> {
        const clients = [...this.clients.values()]
        this.clients.clear()
        await Promise.all(
            clients.map((c) => c.shutdown().catch((err) => this.log.error('shutdown failed', { error: String(err) })))
        )
    }
}
