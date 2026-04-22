import { AppMetricsService } from '../../../common/services/app-metrics.service'
import { IngestionOutputs } from '../../outputs/ingestion-outputs'
import { AppMetricsOutput } from '../outputs'

const APP_SOURCE = 'event_filter'
const METRIC_KIND = 'other'

/**
 * Aggregates event filter app metrics within a batch, flushing them as a
 * single set of Kafka messages after the batch completes.
 *
 * Thin typed adapter around `AppMetricsService` — it constrains the schema to
 * `(team_id, filter_id, metric_name)` and lets the shared service handle
 * dedupe + Kafka production.
 */
export class EventFiltersBatchAppMetrics {
    private readonly service: AppMetricsService

    constructor(outputs: IngestionOutputs<AppMetricsOutput>) {
        this.service = new AppMetricsService(outputs)
    }

    increment(teamId: number, filterId: string, metricName: string): void {
        this.service.queueMetric({
            team_id: teamId,
            app_source: APP_SOURCE,
            app_source_id: filterId,
            metric_kind: METRIC_KIND,
            metric_name: metricName,
            count: 1,
        })
    }

    async flush(): Promise<void> {
        await this.service.flush()
    }
}
