import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    WARPSTREAM_INGESTION_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP,
    WARPSTREAM_LOGS_PRODUCER,
    WARPSTREAM_LOGS_PRODUCER_CONFIG_MAP,
} from './producers'

/**
 * Producers used by the logs/traces ingestion deployments.
 *
 * - `WARPSTREAM_LOGS_PRODUCER` — main log/trace data path (Warpstream logs cluster).
 * - `WARPSTREAM_INGESTION_PRODUCER` — destination for app_metrics rows on the
 *    shared ingestion Warpstream cluster.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_LOGS_PRODUCER, WARPSTREAM_LOGS_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP)
}
