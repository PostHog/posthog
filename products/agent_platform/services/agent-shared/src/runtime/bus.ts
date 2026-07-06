/**
 * Session event bus. Redis pub/sub everywhere (prod, dev, tests). Carries
 * lifecycle events from the runner to listening clients (chat /listen, MCP
 * transport, future telemetry sinks). There is no in-memory variant — the
 * harness runs against a real local Redis with a per-cluster channel prefix
 * so unit-style tests exercise the real round-trip and can't silently drift
 * from prod.
 */

import type { Redis as IoRedis } from 'ioredis'

import { createLogger } from './logger'
import { Counter } from './metrics'

/**
 * Bus health metrics. The bus is critical-path for /listen: the runner
 * publishes lifecycle events, the ingress subscribes and streams them to
 * clients. A publish/subscribe failure means events silently never reach a
 * connected user, so these are the signals for "the live transport is broken."
 */
const busPublishTotal = new Counter({
    name: 'agent_bus_publish_total',
    help: 'Session lifecycle events published to the Redis bus, by outcome (ok/error).',
    labelNames: ['outcome'],
})
const busSubscribeFailures = new Counter({
    name: 'agent_bus_subscribe_failures_total',
    help: 'Failures to SUBSCRIBE a session channel on the Redis bus (the /listen stream gets no events).',
})
const busReceiveErrors = new Counter({
    name: 'agent_bus_receive_errors_total',
    help: 'Errors handling a received bus message, by kind (parse = malformed event, listener = a subscriber threw).',
    labelNames: ['kind'],
})

export type SessionEventKind =
    | 'session_started'
    | 'turn_started'
    /**
     * Fired when the runner drains a user input from `pending_inputs`
     * (i.e. the user message becomes part of the conversation the
     * agent will respond to). Carries `{ text, sender?, timestamp }`.
     * Lets live SSE consumers ground the optimistic local user bubble
     * against server-confirmed conversation order instead of relying
     * on a reload to pick up the authoritative shape.
     */
    | 'user_message'
    | 'assistant_text'
    | 'assistant_text_delta'
    | 'assistant_thinking_delta'
    | 'tool_call'
    | 'tool_call_start'
    | 'tool_call_args_delta'
    | 'tool_result'
    /**
     * Fired when the model calls a `kind: "client"` tool. Carries
     * `{ call_id, tool_id, args }`. The connecting client picks this
     * up over SSE, executes the handler locally, and POSTs the result
     * back to `/sessions/<id>/client_tool_result`. The runner's tool
     * `execute()` is blocked on a matching `client_tool_result` event
     * with the same `call_id`.
     */
    | 'client_tool_call'
    /**
     * Result of a `client_tool_call`. Carries `{ call_id, result }`
     * or `{ call_id, error }`. Published by the ingress endpoint
     * `/sessions/<id>/client_tool_result`; the runner consumes via
     * `bus.subscribe(session_id, …)`.
     */
    | 'client_tool_result'
    /**
     * Inbound stop signal: ingress `/cancel` publishes this on the session
     * channel when a user hits the chat stop button. The runner is already
     * subscribed (same path it consumes `client_tool_result` on) and aborts
     * the in-flight provider call for that turn. Distinct from a worker
     * shutdown — a cancelled run reopens as `completed` (the conversation
     * stays live), it is NOT re-queued. Carries no data.
     */
    | 'cancel'
    /**
     * Outbound acknowledgement that a `cancel` interrupted the in-flight
     * turn. Lets live SSE consumers drop the streaming spinner immediately
     * and reconcile against the partial assistant message the runner
     * persisted. The session state lands `completed` (open), so the user
     * can keep chatting — this event is the UI signal, not a terminal one.
     */
    | 'interrupted'
    /**
     * Default end-of-turn event. Fires for natural stop and meta-end-turn.
     * Session state is `completed` (open). Asking a question is just
     * "respond with text, end the turn" — no separate event.
     */
    | 'completed'
    /**
     * Hard-close event. Fires for `meta-end-session`. Session state is
     * `closed`. SSE consumers should treat this as "stream done" — no
     * further turns unless the trigger config sets `allow_restart`.
     */
    | 'closed'
    | 'failed'
    /**
     * Mid-stream signal that the preview JWT carrying the connection has
     * expired or otherwise stopped validating. Carries
     * `{ reason: 'expired' | 'invalid' }`. Fires from the ingress `/listen`
     * SSE bridge when an upstream re-validation fails between turns; the
     * runner itself never emits this. Consumers (posthog/code agent
     * builder) re-mint a fresh token via `POST .../preview-token/` and
     * re-attach `/listen` transparently. Distinct from `failed` so the UI
     * can render an auth-recovery affordance instead of a generic error.
     * Not a delta event — fires once before the stream closes.
     */
    | 'preview_token_required'

/**
 * High-cardinality delta events that fire many times per turn. Filtered out
 * of the structured log sink (otherwise log_entries becomes unusable for
 * grep / debug) but still publish through the SSE bus for live UIs. The
 * full-text `assistant_text` + full-args `tool_call` events also fire at
 * turn end for consumers (KafkaLogSink, activity log) that want one event
 * per turn-of-event-kind.
 */
export const DELTA_EVENT_KINDS: ReadonlySet<SessionEventKind> = new Set([
    'assistant_text_delta',
    'assistant_thinking_delta',
    'tool_call_start',
    'tool_call_args_delta',
])

export function isDeltaEventKind(kind: SessionEventKind): boolean {
    return DELTA_EVENT_KINDS.has(kind)
}

export interface SessionEvent {
    session_id: string
    kind: SessionEventKind
    data: Record<string, unknown>
    ts: string
}

export interface SessionEventBus {
    publish(event: SessionEvent): Promise<void>
    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void
}

/* -------------------------------------------------------------------------- */
/* Redis pub/sub — the only bus impl. Used by prod, dev, and tests.            */
/* -------------------------------------------------------------------------- */

export interface RedisSessionEventBusOptions {
    // nosemgrep: trailofbits.generic.redis-unencrypted-transport.redis-unencrypted-transport
    /** ioredis-compatible URL, e.g. `redis://localhost:6379`. */
    url: string
    /**
     * Channel prefix. Defaults to `agent_session`. Distinct from v1's
     * `agent_session:` so a co-tenant v1 deployment doesn't see v2 events.
     */
    channelPrefix?: string
}

/**
 * Redis-backed bus for cross-process fan-out — ingress /listen SSE clients
 * connected to host A receive events from runners on host B.
 *
 * Two connections: one for `PUBLISH`, one for `SUBSCRIBE` (ioredis enters a
 * dedicated subscriber state on the connection that issues SUBSCRIBE, so it
 * can't be reused for arbitrary commands). Subscriptions are ref-counted by
 * channel so subscribing N listeners to one session only opens one Redis
 * channel.
 *
 * Lazy-imports `ioredis` so callers that never touch the bus don't pull it
 * in. Call `await bus.connect()` once at boot; `disconnect()` on shutdown.
 */
export class RedisSessionEventBus implements SessionEventBus {
    private readonly opts: Required<RedisSessionEventBusOptions>
    private readonly log = createLogger('redis-bus')
    private readonly subs = new Map<string, Set<(e: SessionEvent) => void>>()
    private publisher: IoRedis | null = null
    private subscriber: IoRedis | null = null
    private connectPromise: Promise<void> | null = null

    constructor(opts: RedisSessionEventBusOptions) {
        this.opts = { channelPrefix: 'agent_session', ...opts }
    }

    async connect(): Promise<void> {
        if (this.connectPromise) {
            return this.connectPromise
        }
        this.connectPromise = (async () => {
            const mod = await import('ioredis')
            const Ctor = (mod as { default?: typeof import('ioredis').default }).default ?? mod
            const RedisCtor = Ctor as unknown as new (url: string) => IoRedis
            this.publisher = new RedisCtor(this.opts.url)
            this.subscriber = new RedisCtor(this.opts.url)
            this.subscriber.on('message', (channel: string, message: string) => {
                const sessionId = this.sessionIdFromChannel(channel)
                if (!sessionId) {
                    return
                }
                const set = this.subs.get(sessionId)
                if (!set) {
                    return
                }
                let event: SessionEvent
                try {
                    event = JSON.parse(message) as SessionEvent
                } catch (err) {
                    busReceiveErrors.labels({ kind: 'parse' }).inc()
                    this.log.warn({ channel, err: (err as Error).message }, 'parse_failed')
                    return
                }
                for (const fn of set) {
                    try {
                        fn(event)
                    } catch (err) {
                        busReceiveErrors.labels({ kind: 'listener' }).inc()
                        this.log.warn({ channel, err: (err as Error).message }, 'listener_threw')
                    }
                }
            })
        })()
        return this.connectPromise
    }

    async publish(event: SessionEvent): Promise<void> {
        if (!this.publisher) {
            await this.connect()
        }
        try {
            await this.publisher!.publish(this.channel(event.session_id), JSON.stringify(event))
            busPublishTotal.labels({ outcome: 'ok' }).inc()
        } catch (err) {
            busPublishTotal.labels({ outcome: 'error' }).inc()
            throw err
        }
    }

    subscribe(sessionId: string, fn: (e: SessionEvent) => void): () => void {
        let set = this.subs.get(sessionId)
        if (!set) {
            set = new Set()
            this.subs.set(sessionId, set)
            // Fire-and-forget — the SUBSCRIBE round-trip is fast, and races
            // are tolerated (the message we miss is at-most one published
            // before the SUBSCRIBE was ACKed; production also tolerates that).
            void this.ensureSubscribed(sessionId)
        }
        set.add(fn)
        return () => {
            const current = this.subs.get(sessionId)
            if (!current) {
                return
            }
            current.delete(fn)
            if (current.size === 0) {
                this.subs.delete(sessionId)
                if (this.subscriber) {
                    void this.subscriber.unsubscribe(this.channel(sessionId)).catch(() => undefined)
                }
            }
        }
    }

    /**
     * Resolves once the Redis SUBSCRIBE for this session's channel has been
     * ACKed. `subscribe()` is deliberately fire-and-forget — prod tolerates
     * missing the at-most-one event published before the ACK, because a
     * long-lived /listen connection attaches before the turn begins. Tests
     * that assert on a *specific* published event have no such slack: they
     * subscribe and then immediately trigger the publish, so they need the
     * channel confirmed live first. Kept off the `SessionEventBus` interface
     * — it's a readiness probe for deterministic tests, not a prod concern.
     */
    async whenSubscribed(sessionId: string): Promise<void> {
        // Guard the precondition: without a registered listener the message
        // handler has no `subs` entry to dispatch to, so it would silently
        // drop every event while this still resolves "channel live" — the
        // exact symptom we're guarding against. Fail loudly instead.
        if (!this.subs.has(sessionId)) {
            throw new Error(`whenSubscribed('${sessionId}') called before subscribe() — register a listener first`)
        }
        await this.ensureSubscribed(sessionId)
    }

    private async ensureSubscribed(sessionId: string): Promise<void> {
        if (!this.subscriber) {
            await this.connect()
        }
        try {
            await this.subscriber!.subscribe(this.channel(sessionId))
        } catch (err) {
            busSubscribeFailures.inc()
            this.log.error({ session_id: sessionId, err: (err as Error).message }, 'subscribe_failed')
        }
    }

    async disconnect(): Promise<void> {
        this.subs.clear()
        const closers: Promise<unknown>[] = []
        if (this.subscriber) {
            closers.push(this.subscriber.quit().catch(() => undefined))
            this.subscriber = null
        }
        if (this.publisher) {
            closers.push(this.publisher.quit().catch(() => undefined))
            this.publisher = null
        }
        await Promise.all(closers)
        this.connectPromise = null
    }

    private channel(sessionId: string): string {
        return `${this.opts.channelPrefix}:${sessionId}`
    }

    private sessionIdFromChannel(channel: string): string | null {
        const prefix = `${this.opts.channelPrefix}:`
        return channel.startsWith(prefix) ? channel.slice(prefix.length) : null
    }
}
