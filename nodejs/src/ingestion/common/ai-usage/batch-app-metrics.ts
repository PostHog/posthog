import { TimestampFormat } from '../../../types'
import { castTimestampOrNow } from '../../../utils/utils'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '../outputs'

interface AggregatedMetric {
    teamId: number
    metricName: string
    count: number
}

/**
 * Aggregates LLM analytics ingestion usage (request byte sizes) within a batch,
 * flushing them as a single set of Kafka messages after the batch completes.
 *
 * Accumulates counts per (teamId, metricName) and produces one app_metrics2
 * message per unique combination at flush time — mirrors the event-filters
 * batch aggregator so a busy batch from one team yields few rows.
 */
export class AiUsageBatchAppMetrics {
    private counts = new Map<string, AggregatedMetric>()

    constructor(private outputs: IngestionOutputs<AppMetricsOutput>) {}

    increment(teamId: number, metricName: string, count: number): void {
        if (count <= 0) {
            return
        }
        const k = `${teamId}:${metricName}`
        const existing = this.counts.get(k)
        if (existing) {
            existing.count += count
        } else {
            this.counts.set(k, { teamId, metricName, count })
        }
    }

    async flush(): Promise<void> {
        const messages = [...this.counts.values()].map(({ teamId, metricName, count }) => ({
            value: Buffer.from(
                JSON.stringify({
                    team_id: teamId,
                    timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                    app_source: 'llm_analytics',
                    app_source_id: '',
                    instance_id: '',
                    metric_kind: 'usage',
                    metric_name: metricName,
                    count,
                })
            ),
            key: Buffer.from(`${teamId}`),
            teamId,
        }))

        this.counts.clear()

        if (messages.length > 0) {
            await this.outputs.queueMessages(APP_METRICS_OUTPUT, messages)
        }
    }
}
