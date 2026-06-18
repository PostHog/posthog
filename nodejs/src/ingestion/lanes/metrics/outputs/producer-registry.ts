import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'

import {
    WARPSTREAM_INGESTION_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP,
    WARPSTREAM_METRICS_PRODUCER,
    WARPSTREAM_METRICS_PRODUCER_CONFIG_MAP,
} from './producers'

/**
 * Producers used by the metrics ingestion deployment.
 *
 * - `WARPSTREAM_METRICS_PRODUCER` — main metrics data path (Warpstream metrics cluster).
 * - `WARPSTREAM_INGESTION_PRODUCER` — destination for app_metrics rows on the
 *    shared ingestion Warpstream cluster.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_METRICS_PRODUCER, WARPSTREAM_METRICS_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP)
}
