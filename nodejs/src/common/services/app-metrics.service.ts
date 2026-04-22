import { TimestampFormat } from '../../types'
import { logger } from '../../utils/logger'
import { castTimestampOrNow } from '../../utils/utils'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '../../ingestion/common/outputs'
import { IngestionOutputs } from '../../ingestion/outputs/ingestion-outputs'

/**
 * A single metric input that callers hand to the service. Aggregation key is
 * `(team_id, app_source, app_source_id, instance_id, metric_kind, metric_name)`
 * — anything sharing those six fields is summed in-memory and emitted as one
 * Kafka message.
 */
export interface AppMetricInput {
    team_id: number
    app_source: string
    app_source_id: string
    instance_id?: string
    metric_kind: string
    metric_name: string
    count: number
}

export interface AppMetricsServiceConfig {
    /**
     * Hard cap on unique buffered keys before a flush is triggered automatically.
     * The flush runs in the background — the producing call is not awaited. Use
     * `waitForBackpressure()` to throttle. Default: 1000.
     */
    maxBufferSize?: number
    /**
     * If set, periodically drains the buffer every N ms. Off by default — the
     * caller is expected to call `flush()` (and `shutdown()` at process exit)
     * unless they opt in here.
     */
    backgroundFlushIntervalMs?: number
}

interface AggregatedMetric extends AppMetricInput {
    instance_id: string
}

const DEFAULT_MAX_BUFFER_SIZE = 1000

/**
 * Buffered, deduping producer for `clickhouse_app_metrics2` (v2 app metrics).
 *
 * Lifecycle:
 * - `queueMetric` is synchronous and aggregates with any existing entry sharing
 *   the same key. Hitting `maxBufferSize` triggers a background flush.
 * - `flush()` drains the buffer to Kafka. Concurrent calls are safely chained:
 *   a flush call always reflects entries queued before it.
 * - `waitForBackpressure()` resolves once any in-flight flush settles. Use it
 *   to throttle producers under load.
 * - `shutdown()` stops the background timer (if enabled) and drains the
 *   buffer one last time. Subsequent `queueMetric` calls throw.
 *
 * Routing decisions (which Kafka cluster, which topic) live in the injected
 * `IngestionOutputs<AppMetricsOutput>` — typically wired from the consumer's
 * monitoring producer in dependency setup.
 */
export class AppMetricsService {
    private buffer = new Map<string, AggregatedMetric>()
    /** Promise of the currently in-flight flush (or null when idle). */
    private inFlight: Promise<void> | null = null
    /** Promise of a flush queued behind the in-flight one (or null). */
    private pending: Promise<void> | null = null
    private timer?: ReturnType<typeof setInterval>
    private isShutdown = false

    private readonly maxBufferSize: number

    constructor(
        private readonly outputs: IngestionOutputs<AppMetricsOutput>,
        config: AppMetricsServiceConfig = {}
    ) {
        this.maxBufferSize = config.maxBufferSize ?? DEFAULT_MAX_BUFFER_SIZE

        if (config.backgroundFlushIntervalMs !== undefined && config.backgroundFlushIntervalMs > 0) {
            this.timer = setInterval(() => {
                this.flush().catch((err) =>
                    logger.error('🔴', 'AppMetricsService background flush failed', { error: err })
                )
            }, config.backgroundFlushIntervalMs)
        }
    }

    /** Aggregate one metric into the buffer. Synchronous. */
    queueMetric(metric: AppMetricInput): void {
        if (this.isShutdown) {
            throw new Error('AppMetricsService.queueMetric called after shutdown')
        }
        const key = makeKey(metric)
        const existing = this.buffer.get(key)
        if (existing) {
            existing.count += metric.count
        } else {
            this.buffer.set(key, { ...metric, instance_id: metric.instance_id ?? '' })
        }
        if (this.buffer.size >= this.maxBufferSize) {
            // Fire-and-forget; callers can await `waitForBackpressure()` to throttle.
            void this.flush().catch((err) =>
                logger.error('🔴', 'AppMetricsService buffer-full flush failed', { error: err })
            )
        }
    }

    /** Convenience for batched producers. */
    queueMetrics(metrics: AppMetricInput[]): void {
        for (const metric of metrics) {
            this.queueMetric(metric)
        }
    }

    /**
     * Drain the buffer and produce to Kafka. Returns a promise that resolves
     * once every entry queued before the call has been delivered.
     *
     * If a flush is already in flight, the new call chains behind it so no
     * caller misses entries that landed during the previous flush.
     */
    flush(): Promise<void> {
        if (this.inFlight) {
            // A flush is already running. Make sure exactly one follow-up flush
            // is scheduled after it, and have all callers in this window share
            // its promise — otherwise N concurrent callers would each schedule
            // their own follow-up.
            if (!this.pending) {
                this.pending = this.inFlight.then(() => {
                    this.pending = null
                    return this.flush()
                })
            }
            return this.pending
        }
        if (this.buffer.size === 0) {
            return Promise.resolve()
        }
        const drained = this.buffer
        this.buffer = new Map()
        this.inFlight = this._produce(drained).finally(() => {
            this.inFlight = null
        })
        return this.inFlight
    }

    /**
     * Resolve when any in-flight flush settles. No-op when nothing is in flight.
     * Intended as a backpressure signal — callers can await this to slow down
     * before the next produce.
     */
    async waitForBackpressure(): Promise<void> {
        if (this.inFlight) {
            await this.inFlight.catch(() => undefined)
        }
    }

    /**
     * Stop the background timer (if enabled), drain the buffer one last time,
     * and reject any further `queueMetric` calls. Idempotent.
     */
    async shutdown(): Promise<void> {
        if (this.isShutdown) {
            await this.waitForBackpressure()
            return
        }
        this.isShutdown = true
        if (this.timer) {
            clearInterval(this.timer)
            this.timer = undefined
        }
        await this.flush()
    }

    private async _produce(drained: Map<string, AggregatedMetric>): Promise<void> {
        const timestamp = castTimestampOrNow(null, TimestampFormat.ClickHouse)
        const messages = [...drained.values()].map((m) => ({
            value: Buffer.from(
                JSON.stringify({
                    team_id: m.team_id,
                    timestamp,
                    app_source: m.app_source,
                    app_source_id: m.app_source_id,
                    instance_id: m.instance_id,
                    metric_kind: m.metric_kind,
                    metric_name: m.metric_name,
                    count: m.count,
                })
            ),
            key: Buffer.from(`${m.team_id}`),
        }))
        await this.outputs.queueMessages(APP_METRICS_OUTPUT, messages)
    }
}

function makeKey(m: AppMetricInput): string {
    return `${m.team_id}:${m.app_source}:${m.app_source_id}:${m.instance_id ?? ''}:${m.metric_kind}:${m.metric_name}`
}
