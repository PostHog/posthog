/**
 * LogSink — the runner's structured-log out-bound. Each session lifecycle
 * event becomes a row in the team's `log_entries` ClickHouse table, via
 * Kafka (same pipeline CDP uses, same shape v1's agent-runner wrote):
 *
 *   runner ─Kafka─▶ topic: log_entries ─consumer─▶ log_entries (CH)
 *
 * `KafkaLogSink` is the only impl — used by prod, dev, and tests (the harness
 * connects against the local Kafka broker via `bin/start`). Tests assert on
 * the wire payloads via the `tap` callback rather than polling ClickHouse
 * (the CH materialised view is asynchronous and flakey under load). The tap
 * fires synchronously before each `produce()` so a passing assertion means
 * the producer was actually invoked with the expected wire bytes; the
 * downstream CH write is exercised end-to-end in prod.
 *
 * Internal `LogEntry` shape is the structured event+data one — useful for
 * test assertions and downstream consumers. The Kafka writer translates it
 * to v1's flat `[kind] …` message format on the wire so the existing CH
 * materialized view picks rows up without changes.
 */

import type { HighLevelProducer, LibrdKafkaError, Metadata, ProducerGlobalConfig } from 'node-rdkafka'
import { hostname } from 'node:os'

import { createLogger } from './logger'
import { Counter } from './metrics'

/**
 * Log-sink throughput by outcome. The runner's only path to the `log_entries`
 * ClickHouse table (which backs the console's session-detail timeline) is this
 * fire-and-forget Kafka producer, so a rising `dropped` / `error` rate means
 * per-turn logs are silently not reaching the console. `produced` = handed to
 * rdkafka (batched on the wire), not delivery-confirmed.
 */
const logSinkEntries = new Counter({
    name: 'agent_logsink_entries_total',
    help: 'Log entries handled by the Kafka log sink, by outcome (produced/dropped/error).',
    labelNames: ['outcome'],
})

export type LogLevel = 'debug' | 'info' | 'warn' | 'error'

/**
 * Structured log entry as the runner emits it. Same identifying fields as
 * v1's CH row (team / app / session / timestamp / level), plus our structured
 * `event` + `data` for typed consumers and tests.
 */
export interface LogEntry {
    /** ISO-8601 (UTC) timestamp. */
    ts: string
    team_id: number
    application_id: string
    session_id: string
    level: LogLevel
    /** Stable event name: "session_started", "turn_started", "tool_call", "tool_result", "completed", "waiting", "failed". */
    event: string
    /** Free-form structured data — serialized into the wire message. */
    data: Record<string, unknown>
}

export const AGENT_SESSION_LOG_SOURCE = 'agent_session'

export interface LogSink {
    write(entries: LogEntry[]): Promise<void>
}

/* -------------------------------------------------------------------------- */
/* Wire format — what the CH consumer expects on the Kafka topic              */
/* -------------------------------------------------------------------------- */

/**
 * v1 CH row shape. Mirrors `services/agent-core/src/log-entries/types.ts`.
 * Field names + level case match the existing `log_entries` table.
 */
export interface LogEntryWire {
    team_id: number
    /** `agent_session` for everything emitted by the runner. */
    log_source: string
    /** AgentApplication UUID (string form). */
    log_source_id: string
    /** Session UUID (string form). */
    instance_id: string
    /** ISO timestamp with microsecond precision (matches `DateTime64(6, 'UTC')`). */
    timestamp: string
    level: 'DEBUG' | 'INFO' | 'WARNING' | 'ERROR'
    /** Flat human-readable line with a `[kind]` prefix. */
    message: string
}

/** Mapping from our structured `event` → v1's flat-message `[kind]` prefix. */
const EVENT_KIND: Record<string, string> = {
    session_started: '[meta]',
    turn_started: '[meta]',
    assistant_text: '[chat]',
    tool_call: '[tool]',
    tool_result: '[tool]',
    completed: '[event]',
    waiting: '[event]',
    failed: '[error]',
}

const LEVEL_MAP: Record<LogLevel, LogEntryWire['level']> = {
    debug: 'DEBUG',
    info: 'INFO',
    warn: 'WARNING',
    error: 'ERROR',
}

export function toWire(entry: LogEntry): LogEntryWire {
    const kind = EVENT_KIND[entry.event] ?? '[event]'
    const message = `${kind} ${entry.event}${Object.keys(entry.data).length ? ' ' + JSON.stringify(entry.data) : ''}`
    return {
        team_id: entry.team_id,
        log_source: AGENT_SESSION_LOG_SOURCE,
        log_source_id: entry.application_id,
        instance_id: entry.session_id,
        timestamp: toClickhouseDateTime64(entry.ts),
        level: LEVEL_MAP[entry.level],
        message,
    }
}

/**
 * CH `DateTime64(6, 'UTC')` parser (used by the Kafka engine on read)
 * rejects the `T...Z` ISO suffix. Convert to the form CH actually
 * accepts: `YYYY-MM-DD HH:MM:SS.uuuuuu`. Inputs are ISO-8601 strings
 * (millisecond precision); we right-pad to microsecond precision.
 */
export function toClickhouseDateTime64(iso: string): string {
    // 2026-05-29T12:55:58.532Z → 2026-05-29 12:55:58.532000
    const stripped = iso.replace('T', ' ').replace(/Z$/, '')
    const dotIdx = stripped.indexOf('.')
    if (dotIdx === -1) {
        return `${stripped}.000000`
    }
    const fractional = stripped.slice(dotIdx + 1)
    return `${stripped.slice(0, dotIdx)}.${fractional.padEnd(6, '0').slice(0, 6)}`
}

/* -------------------------------------------------------------------------- */
/* Kafka sink — production path. Ports services/agent-core/src/log-entries.   */
/* -------------------------------------------------------------------------- */

export interface KafkaLogSinkOptions {
    /** Comma-separated brokers, e.g. `kafka:9092`. */
    brokers: string
    /** Defaults to `log_entries`. */
    topic?: string
    /** Optional rdkafka overrides; merged over the defaults. */
    config?: Partial<ProducerGlobalConfig>
    /** Optional name for log lines / metrics labels. Defaults to topic. */
    name?: string
    /**
     * Optional logger for connection / failure events. Defaults to `console`.
     * Production wires pino here.
     */
    logger?: {
        info: (msg: string, meta?: unknown) => void
        warn: (msg: string, meta?: unknown) => void
        error: (msg: string, meta?: unknown) => void
    }
    /**
     * Synchronous side channel called per entry *before* `producer.produce()`.
     * Tests wire this to accumulate the wire payloads for assertion — that
     * way we validate the producer was invoked with the right bytes without
     * paying the ClickHouse materialised-view round-trip latency (which is
     * asynchronous and flakey under load). The tap sees the same `LogEntry`
     * the runner emitted plus the translated `LogEntryWire`; assertions
     * usually grep on the structured fields and ignore the wire envelope.
     */
    tap?: (entry: LogEntry, wire: LogEntryWire) => void
}

/**
 * Sensible defaults for a low-volume, fire-and-forget producer. Tuned the
 * same way v1's producer was: rdkafka handles batching natively via
 * `linger.ms` + `batch.size`, no in-process buffer.
 */
const DEFAULT_PRODUCER_CONFIG: ProducerGlobalConfig = {
    'client.id': hostname(),
    'linger.ms': 20,
    'batch.size': 8 * 1024 * 1024,
    'queue.buffering.max.messages': 100_000,
    'compression.codec': 'snappy',
    'metadata.max.age.ms': 30_000,
    'socket.timeout.ms': 30_000,
}

/**
 * Production Kafka writer. Wraps node-rdkafka's HighLevelProducer.
 *
 * Lifecycle:
 *   const sink = new KafkaLogSink({ brokers: 'kafka:9092' })
 *   await sink.connect()                             // once at boot
 *   // runner calls sink.write([entry, …]) per turn
 *   await sink.disconnect()                          // once at shutdown
 *
 * `node-rdkafka` is loaded via dynamic import the first time `connect()` is
 * called — packages that never construct a KafkaLogSink (tests, dev w/ Noop)
 * don't pay the native-module cost at import time.
 */
export class KafkaLogSink implements LogSink {
    private readonly opts: KafkaLogSinkOptions
    private readonly log: NonNullable<KafkaLogSinkOptions['logger']>
    private producer: HighLevelProducer | null = null
    private connected = false
    private connectPromise: Promise<void> | null = null
    private disposed = false

    constructor(opts: KafkaLogSinkOptions) {
        this.opts = opts
        if (opts.logger) {
            this.log = opts.logger
        } else {
            const pino = createLogger('kafka-log', { topic: opts.topic ?? 'log_entries' })
            this.log = {
                info: (m, meta) => pino.info(meta ?? {}, m),
                warn: (m, meta) => pino.warn(meta ?? {}, m),
                error: (m, meta) => pino.error(meta ?? {}, m),
            }
        }
    }

    async connect(): Promise<void> {
        if (this.connected) {
            return
        }
        if (!this.connectPromise) {
            this.connectPromise = this.doConnect()
        }
        return this.connectPromise
    }

    private async doConnect(): Promise<void> {
        // Lazy import so dev / test code paths don't need a native librdkafka.
        // node-rdkafka ships as CommonJS so the namespace import lands the
        // exports on `.default` under Node's ESM/CJS interop — fall back if
        // future versions switch to a real ESM build.
        const mod = await import('node-rdkafka')
        const rdkafka: typeof import('node-rdkafka') =
            (mod as unknown as { default?: typeof import('node-rdkafka') }).default ?? mod
        const merged: ProducerGlobalConfig = {
            ...DEFAULT_PRODUCER_CONFIG,
            'metadata.broker.list': this.opts.brokers,
            ...this.opts.config,
            dr_cb: false,
        }
        const producer = new rdkafka.HighLevelProducer(merged)
        producer.on('event.error', (err: LibrdKafkaError) =>
            this.log.error('rdkafka error', { name: this.opts.name ?? this.opts.topic, error: String(err) })
        )
        await new Promise<void>((resolve, reject) => {
            producer.connect(undefined, (err: LibrdKafkaError, data: Metadata) => {
                if (err) {
                    reject(err)
                    return
                }
                this.log.info('kafka log producer connected', {
                    name: this.opts.name ?? this.opts.topic,
                    topic: this.opts.topic ?? 'log_entries',
                    brokers: (data as { brokers?: unknown })?.brokers,
                })
                resolve()
            })
        })
        this.producer = producer
        this.connected = true
    }

    /**
     * Fire-and-forget batch write. Entries are individually produced; rdkafka
     * batches on the wire via `linger.ms`. Drops on broker failure (logged via
     * the rdkafka `event.error` handler) so the runner never blocks on logs.
     */
    async write(entries: LogEntry[]): Promise<void> {
        if (this.disposed) {
            return
        }
        if (!this.connected || !this.producer) {
            logSinkEntries.labels({ outcome: 'dropped' }).inc(entries.length)
            this.log.warn('dropping entries (not connected)', { count: entries.length })
            return
        }
        const topic = this.opts.topic ?? 'log_entries'
        for (const entry of entries) {
            const wire = toWire(entry)
            if (this.opts.tap) {
                try {
                    this.opts.tap(entry, wire)
                } catch (err) {
                    this.log.warn('tap threw', { error: String(err) })
                }
            }
            const value = Buffer.from(safeClickhouseString(JSON.stringify(wire)))
            try {
                this.producer.produce(topic, null, value, null, Date.now(), noopDeliveryCallback)
                logSinkEntries.labels({ outcome: 'produced' }).inc()
            } catch (err) {
                logSinkEntries.labels({ outcome: 'error' }).inc()
                this.log.error('produce failed', { topic, error: String(err) })
            }
        }
    }

    async disconnect(): Promise<void> {
        this.disposed = true
        if (!this.connected || !this.producer) {
            return
        }
        const producer = this.producer
        await new Promise<void>((resolve) =>
            producer.flush(5_000, () => {
                resolve()
            })
        )
        await new Promise<void>((resolve) =>
            producer.disconnect(() => {
                resolve()
            })
        )
        this.connected = false
        this.producer = null
    }
}

/** HighLevelProducer requires a delivery callback; we ignore it (fire-and-forget). */
function noopDeliveryCallback(): void {
    /* intentionally empty */
}

/**
 * ClickHouse's JSON parser rejects lone Unicode surrogates. The CDP pipeline
 * escapes them before producing onto Kafka so the consumer doesn't have to.
 * Vendored from `services/agent-core/src/log-entries/safe-clickhouse-string.ts`.
 */
function safeClickhouseString(str: string): string {
    return str.replace(/[\ud800-\udfff]/gu, (match) => {
        const res = JSON.stringify(match)
        return res.slice(1, res.length - 1) + `\\`
    })
}
