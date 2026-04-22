import { AggregatingProducer } from '../../../common/services/aggregating-producer'
import { AppMetricInput, createAppMetricsProducer } from '../../../common/services/app-metrics'
import { IngestionOutput } from '../../outputs/ingestion-output'

const APP_SOURCE = 'event_filter'
const METRIC_KIND = 'other'

/**
 * Aggregates event filter app metrics within a batch, flushing them as a
 * single set of Kafka messages after the batch completes.
 *
 * Thin typed adapter around the shared `AggregatingProducer` — it constrains
 * the schema to `(team_id, filter_id, metric_name)` and delegates dedupe +
 * Kafka production.
 */
export class EventFiltersBatchAppMetrics {
    private readonly producer: AggregatingProducer<AppMetricInput>

    constructor(output: IngestionOutput) {
        this.producer = createAppMetricsProducer(output)
    }

    increment(teamId: number, filterId: string, metricName: string): void {
        this.producer.queue({
            team_id: teamId,
            app_source: APP_SOURCE,
            app_source_id: filterId,
            metric_kind: METRIC_KIND,
            metric_name: metricName,
            count: 1,
        })
    }

    async flush(): Promise<void> {
        await this.producer.flush()
    }
}
