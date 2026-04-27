import { TimestampFormat } from '../../../types'
import { castTimestampOrNow } from '../../../utils/utils'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { APP_METRICS_OUTPUT, AppMetricsOutput } from '../outputs'

interface AggregatedMetric {
    teamId: number
    filterId: string
    metricName: string
    count: number
}

/**
 * Aggregates event filter app metrics within a batch, flushing them as a
 * single set of Kafka messages after the batch completes.
 *
 * Instead of producing one Kafka message per matched event, this accumulates
 * counts per (teamId, filterId, metricName) and produces one message per unique
 * combination at flush time.
 */
export class EventFiltersBatchAppMetrics {
    private counts = new Map<string, AggregatedMetric>()

    constructor(private outputs: IngestionOutputs<AppMetricsOutput>) {}

    increment(teamId: number, filterId: string, metricName: string): void {
        const k = `${teamId}:${filterId}:${metricName}`
        const existing = this.counts.get(k)
        if (existing) {
            existing.count++
        } else {
            this.counts.set(k, { teamId, filterId, metricName, count: 1 })
        }
    }

    async flush(): Promise<void> {
        const messages = [...this.counts.values()].map(({ teamId, filterId, metricName, count }) => ({
            value: Buffer.from(
                JSON.stringify({
                    team_id: teamId,
                    timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                    app_source: 'event_filter',
                    app_source_id: filterId,
                    metric_kind: 'other',
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
