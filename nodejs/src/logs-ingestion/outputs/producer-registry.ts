import { INGESTION_PRODUCER_CONFIG_MAP } from '../../ingestion/common/config'
import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    MSK_PRODUCER,
    MSK_PRODUCER_CONFIG_MAP,
    WARPSTREAM_INGESTION_PRODUCER,
    WARPSTREAM_LOGS_PRODUCER,
    WARPSTREAM_LOGS_PRODUCER_CONFIG_MAP,
} from './producers'

/**
 * Producers used by the logs/traces ingestion deployments.
 *
 * - `WARPSTREAM_LOGS_PRODUCER` — main log/trace data path (Warpstream logs cluster).
 * - `MSK_PRODUCER` — current default destination for app_metrics rows.
 * - `WARPSTREAM_INGESTION_PRODUCER` — alternate destination for app_metrics,
 *    enabled by setting `LOGS_INGESTION_OUTPUT_APP_METRICS_PRODUCER` to flip
 *    the route off MSK and onto the shared ingestion Warpstream cluster.
 *    Reuses the existing `KAFKA_INGESTION_PRODUCER_*` env vars.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_LOGS_PRODUCER, WARPSTREAM_LOGS_PRODUCER_CONFIG_MAP)
        .register(MSK_PRODUCER, MSK_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_INGESTION_PRODUCER, INGESTION_PRODUCER_CONFIG_MAP)
}
