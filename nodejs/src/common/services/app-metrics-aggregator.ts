import { DateTime } from 'luxon'
import { Counter } from 'prom-client'

import { APP_METRICS_OUTPUT, AppMetricsOutput } from '~/common/outputs'
import { IngestionOutputs } from '~/common/outputs/ingestion-outputs'
import { safeClickhouseString } from '~/common/utils/db/utils'
import { castTimestampOrNow, castTimestampToClickhouseFormat } from '~/common/utils/utils'

import { ClickHouseTimestamp, TimestampFormat } from '../../types'

const appMetricsAggregatorQueuedCounter = new Counter({
    name: 'app_metrics_aggregator_queued_total',
    help: 'App metric items queued — counted before in-memory dedup.',
    labelNames: ['app_source'],
})

const appMetricsAggregatorFlushedCounter = new Counter({
    name: 'app_metrics_aggregator_flushed_total',
    help: 'Unique app metric rows produced to Kafka after in-memory dedup. Dedup rate = 1 - (flushed / queued).',
    labelNames: ['app_source'],
})

/**
 * One v2 app metric row, matching the ClickHouse `app_metrics2` schema.
 * Aggregation key is the six identity fields plus the timestamp hour — entries
 * sharing them have their `count` summed in-memory and emitted as one Kafka
 * message on `flush`.
 */
export interface AppMetricInput {
    team_id: number
    app_source: string
    app_source_id: string
    instance_id?: string
    metric_kind: string
    metric_name: string
    count: number
    /**
     * Defaults to the flush time. Set it to date the row at another hour, e.g. a future
     * month of logs retention that should bill when that month starts. Truncated to the hour,
     * the same grain `app_metrics2` aggregates at.
     */
    timestamp?: DateTime
}

type BufferedAppMetric = Omit<AppMetricInput, 'instance_id' | 'timestamp'> & {
    instance_id: string
    timestamp: ClickHouseTimestamp | null
}

export interface AppMetricsAggregatorOptions {
    /**
     * Keeps rows buffered until this many milliseconds have passed since the last produce, so that
     * repeats of one key collapse across several flushes instead of only within one.
     *
     * A caller that flushes once per Kafka batch gets almost no dedup, because a single batch
     * rarely repeats a key. Spanning several seconds of batches is what makes the keys repeat.
     *
     * The cost is delay and durability: a row waits up to this long, and a pod that exits without
     * `flush(true)` loses what it still holds. Leave it at 0 for a caller whose rows must not be
     * delayed or dropped, such as billing.
     */
    minFlushIntervalMs?: number
}

// A buffer only shrinks when keys repeat. This caps the rows one window can hold, so a caller with
// unexpectedly high key cardinality produces early instead of growing the heap until the window ends.
export const MAX_BUFFERED_ROWS = 10_000

/**
 * Dedupes v2 app metrics on `queue`, produces them on `flush`.
 *
 * The Kafka routing decision (which producer, which topic) is injected as an
 * `IngestionOutputs` registry that must include `APP_METRICS_OUTPUT`. The
 * aggregator pulls the resolved output by name on `flush`. No background
 * flushing, no lifecycle — caller is expected to `flush()` at the end of
 * whatever batch / cycle they want metrics emitted for.
 */
export class AppMetricsAggregator {
    private buffer = new Map<string, BufferedAppMetric>()
    private readonly minFlushIntervalMs: number
    private lastFlushAt = Date.now()
    private drainTimer: NodeJS.Timeout | null = null
    private drainInFlight: Promise<void> | null = null

    constructor(
        private readonly outputs: IngestionOutputs<AppMetricsOutput>,
        options: AppMetricsAggregatorOptions = {}
    ) {
        this.minFlushIntervalMs = options.minFlushIntervalMs ?? 0
        if (this.minFlushIntervalMs > 0) {
            // A caller only flushes while it has work. Without this, the rows a quiet pod still holds
            // wait for its next batch, which may be far longer than the interval, or never come.
            this.drainTimer = setInterval(() => {
                // Forced, so a caller flush that landed just after the previous tick cannot push
                // these rows into the tick after this one and double the delay the window promises.
                // flush() serializes the produce itself, so this cannot start a second one.
                void this.flush(true).catch(() => {
                    // flush() reports its own failures through the caller. A rejection here has no
                    // caller, and an unhandled one would take the process down.
                })
            }, this.minFlushIntervalMs)
            // The timer must not be the reason the process stays alive.
            this.drainTimer.unref()
        }
    }

    /** Produces what is buffered and stops the background drain. */
    async stop(): Promise<void> {
        if (this.drainTimer) {
            clearInterval(this.drainTimer)
            this.drainTimer = null
        }
        await this.flush(true)
    }

    queue(metric: AppMetricInput): void {
        appMetricsAggregatorQueuedCounter.inc({ app_source: metric.app_source })
        const { timestamp, ...rest } = metric
        const row: BufferedAppMetric = {
            ...rest,
            instance_id: metric.instance_id ?? '',
            timestamp: timestamp
                ? castTimestampToClickhouseFormat(timestamp.toUTC().startOf('hour'), TimestampFormat.ClickHouse)
                : null,
        }
        const key = makeKey(row)
        const existing = this.buffer.get(key)
        if (existing) {
            existing.count += metric.count
        } else {
            this.buffer.set(key, row)
        }
    }

    /** Pass `force` to produce whatever is buffered regardless of `minFlushIntervalMs`, as on shutdown. */
    async flush(force = false): Promise<void> {
        if (this.buffer.size === 0) {
            return
        }
        if (!force && this.buffer.size < MAX_BUFFERED_ROWS && Date.now() - this.lastFlushAt < this.minFlushIntervalMs) {
            return
        }
        // One produce at a time. This empties the buffer before the produce resolves, so a second
        // one started underneath it would hold both batches in memory, past the row cap, and queue
        // both on the producer that billing rows also use.
        if (this.drainInFlight) {
            if (!force) {
                return
            }
            await this.drainInFlight
            if (this.buffer.size === 0) {
                return
            }
        }
        this.drainInFlight = this.produce().finally(() => {
            this.drainInFlight = null
        })
        await this.drainInFlight
    }

    private async produce(): Promise<void> {
        this.lastFlushAt = Date.now()
        const drained = [...this.buffer.values()]
        this.buffer.clear()

        const flushTimestamp = castTimestampOrNow(null, TimestampFormat.ClickHouse)
        // No partition key — rows are re-aggregated by ClickHouse, ordering is
        // irrelevant, and round-robin distributes load evenly across partitions.
        const messages = drained.map((m) => ({
            value: Buffer.from(
                // safeClickhouseString strips lone Unicode surrogates that ClickHouse rejects —
                // identity fields are PostHog-generated UUIDs today, but cheap insurance if
                // any of them ever take user-controlled values.
                safeClickhouseString(
                    JSON.stringify({
                        team_id: m.team_id,
                        timestamp: m.timestamp ?? flushTimestamp,
                        app_source: m.app_source,
                        app_source_id: m.app_source_id,
                        instance_id: m.instance_id,
                        metric_kind: m.metric_kind,
                        metric_name: m.metric_name,
                        count: m.count,
                    })
                )
            ),
            key: null,
        }))
        await this.outputs.queueMessages(APP_METRICS_OUTPUT, messages)

        // Increment after the await so a failed produce isn't counted as flushed —
        // dedup-rate = 1 - (flushed / queued) stays meaningful in error scenarios.
        for (const m of drained) {
            appMetricsAggregatorFlushedCounter.inc({ app_source: m.app_source })
        }
    }
}

function makeKey(m: BufferedAppMetric): string {
    return `${m.team_id}:${m.app_source}:${m.app_source_id}:${m.instance_id}:${m.metric_kind}:${m.metric_name}:${m.timestamp ?? ''}`
}
