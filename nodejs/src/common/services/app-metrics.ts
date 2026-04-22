import { IngestionOutput } from '../../ingestion/outputs/ingestion-output'
import { TimestampFormat } from '../../types'
import { castTimestampOrNow } from '../../utils/utils'
import { AggregatingProducer, AggregatingProducerOptions } from './aggregating-producer'

/**
 * One v2 app metric row, matching the ClickHouse `app_metrics2` schema.
 * Aggregation key (set in the factory below): the six identity fields.
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

interface AggregatedAppMetric extends AppMetricInput {
    instance_id: string
}

export type AppMetricsProducerConfig = Pick<
    AggregatingProducerOptions<AppMetricInput>,
    'maxBufferSize' | 'backgroundFlushIntervalMs'
>

/**
 * Build an `AggregatingProducer` configured for the v2 `clickhouse_app_metrics2`
 * schema. Callers inject the `IngestionOutput` so they decide which producer +
 * topic to write to (e.g. monitoring producer, MSK producer, ad-hoc).
 *
 * Aggregation key:
 *   `(team_id, app_source, app_source_id, instance_id, metric_kind, metric_name)`
 * — anything sharing those six fields is summed in-memory and emitted as one
 * Kafka message at flush time.
 */
export function createAppMetricsProducer(
    output: IngestionOutput,
    config: AppMetricsProducerConfig = {}
): AggregatingProducer<AppMetricInput> {
    return new AggregatingProducer<AppMetricInput>(output, {
        key: (m) =>
            `${m.team_id}:${m.app_source}:${m.app_source_id}:${m.instance_id ?? ''}:${m.metric_kind}:${m.metric_name}`,
        merge: (existing, incoming) => ({ ...existing, count: existing.count + incoming.count }),
        serialize: (m) => {
            const row: AggregatedAppMetric & { timestamp: string } = {
                team_id: m.team_id,
                timestamp: castTimestampOrNow(null, TimestampFormat.ClickHouse),
                app_source: m.app_source,
                app_source_id: m.app_source_id,
                instance_id: m.instance_id ?? '',
                metric_kind: m.metric_kind,
                metric_name: m.metric_name,
                count: m.count,
            }
            return Buffer.from(JSON.stringify(row))
        },
        ...config,
    })
}
