import { Counter } from 'prom-client'

import { IngestionOutput } from '../../ingestion/outputs/ingestion-output'
import { TimestampFormat } from '../../types'
import { safeClickhouseString } from '../../utils/db/utils'
import { castTimestampOrNow } from '../../utils/utils'

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
 * Aggregation key is the six identity fields — entries sharing them have
 * their `count` summed in-memory and emitted as one Kafka message on `flush`.
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

/**
 * Dedupes v2 app metrics on `queue`, produces them on `flush`.
 *
 * The Kafka routing decision (which producer, which topic) is injected as an
 * `IngestionOutput` — callers build and hand in whichever output they want.
 * No background flushing, no lifecycle — caller is expected to `flush()` at
 * the end of whatever batch / cycle they want metrics emitted for.
 */
export class AppMetricsAggregator {
    private buffer = new Map<string, AppMetricInput & { instance_id: string }>()

    constructor(private readonly output: IngestionOutput) {}

    queue(metric: AppMetricInput): void {
        appMetricsAggregatorQueuedCounter.inc({ app_source: metric.app_source })
        const key = makeKey(metric)
        const existing = this.buffer.get(key)
        if (existing) {
            existing.count += metric.count
        } else {
            this.buffer.set(key, { ...metric, instance_id: metric.instance_id ?? '' })
        }
    }

    async flush(): Promise<void> {
        if (this.buffer.size === 0) {
            return
        }
        const drained = [...this.buffer.values()]
        this.buffer.clear()

        const timestamp = castTimestampOrNow(null, TimestampFormat.ClickHouse)
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
                        timestamp,
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
        await this.output.queueMessages(messages)

        // Increment after the await so a failed produce isn't counted as flushed —
        // dedup-rate = 1 - (flushed / queued) stays meaningful in error scenarios.
        for (const m of drained) {
            appMetricsAggregatorFlushedCounter.inc({ app_source: m.app_source })
        }
    }
}

function makeKey(m: AppMetricInput): string {
    return `${m.team_id}:${m.app_source}:${m.app_source_id}:${m.instance_id ?? ''}:${m.metric_kind}:${m.metric_name}`
}
