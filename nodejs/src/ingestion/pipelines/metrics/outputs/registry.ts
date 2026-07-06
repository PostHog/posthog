import { APP_METRICS_OUTPUT } from '~/common/outputs'
import { IngestionOutputsBuilder } from '~/common/outputs/ingestion-outputs-builder'

import { METRICS_DLQ_OUTPUT, METRICS_OUTPUT } from './outputs'

/**
 * Outputs for the metrics ingestion deployment.
 *
 * - `METRICS_OUTPUT` — main metrics data path → topic from `METRICS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC`.
 * - `METRICS_DLQ_OUTPUT` — DLQ for failed messages → topic from `METRICS_INGESTION_CONSUMER_DLQ_TOPIC`.
 * - `APP_METRICS_OUTPUT` — usage metrics → topic from `METRICS_INGESTION_OUTPUT_APP_METRICS_TOPIC`.
 *
 * Per-output producer is env-controlled (`*_PRODUCER` keys) so the route can be
 * flipped between Warpstream-metrics / Warpstream-ingestion without code changes.
 */
export function createMetricsOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'METRICS_INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'METRICS_INGESTION_OUTPUT_APP_METRICS_PRODUCER',
        })
        .register(METRICS_OUTPUT, {
            topicKey: 'METRICS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC',
            producerKey: 'METRICS_INGESTION_OUTPUT_METRICS_PRODUCER',
        })
        .register(METRICS_DLQ_OUTPUT, {
            topicKey: 'METRICS_INGESTION_CONSUMER_DLQ_TOPIC',
            producerKey: 'METRICS_INGESTION_OUTPUT_DLQ_PRODUCER',
        })
}
