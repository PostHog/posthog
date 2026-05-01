import { APP_METRICS_OUTPUT } from '../../ingestion/common/outputs'
import { IngestionOutputsBuilder } from '../../ingestion/outputs/ingestion-outputs-builder'
import { LOGS_DLQ_OUTPUT, LOGS_OUTPUT } from './outputs'

/**
 * Outputs for the logs ingestion deployment.
 *
 * - `LOGS_OUTPUT` — main log data path → topic from `LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC`.
 * - `LOGS_DLQ_OUTPUT` — DLQ for failed messages → topic from `LOGS_INGESTION_CONSUMER_DLQ_TOPIC`.
 * - `APP_METRICS_OUTPUT` — usage metrics → topic from `LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC`.
 *
 * Per-output producer is env-controlled (`*_PRODUCER` keys) so the route can be
 * flipped between MSK / Warpstream-logs / Warpstream-ingestion without code changes.
 */
export function createLogsOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER',
        })
        .register(LOGS_OUTPUT, {
            topicKey: 'LOGS_INGESTION_CONSUMER_CLICKHOUSE_TOPIC',
            producerKey: 'LOGS_INGESTION_OUTPUT_LOGS_PRODUCER',
        })
        .register(LOGS_DLQ_OUTPUT, {
            topicKey: 'LOGS_INGESTION_CONSUMER_DLQ_TOPIC',
            producerKey: 'LOGS_INGESTION_OUTPUT_DLQ_PRODUCER',
        })
}

/**
 * Outputs for the traces ingestion deployment. Mirrors `createLogsOutputsRegistry`
 * but reads topic names from the traces-prefixed env vars so a single deployment
 * type produces to the trace-specific topics.
 */
export function createTracesOutputsRegistry() {
    return new IngestionOutputsBuilder()
        .register(APP_METRICS_OUTPUT, {
            topicKey: 'LOGS_INGESTION_OUTPUT_APP_METRICS_TOPIC',
            producerKey: 'LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER',
        })
        .register(LOGS_OUTPUT, {
            topicKey: 'TRACES_INGESTION_CONSUMER_CLICKHOUSE_TOPIC',
            producerKey: 'LOGS_INGESTION_OUTPUT_LOGS_PRODUCER',
        })
        .register(LOGS_DLQ_OUTPUT, {
            topicKey: 'TRACES_INGESTION_CONSUMER_DLQ_TOPIC',
            producerKey: 'LOGS_INGESTION_OUTPUT_DLQ_PRODUCER',
        })
}
