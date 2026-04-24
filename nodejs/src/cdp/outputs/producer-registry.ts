import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    MSK_PRODUCER,
    MSK_PRODUCER_CONFIG_MAP,
    WAREHOUSE_PRODUCER,
    WAREHOUSE_PRODUCER_CONFIG_MAP,
    WARPSTREAM_INGESTION_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP,
} from './producers'

/**
 * Producers used by the CDP deployments.
 *
 * - `WARPSTREAM_INGESTION_PRODUCER` — hog function monitoring (app metrics +
 *   log entries). Targets the warpstream-ingestion cluster via
 *   `KAFKA_WARPSTREAM_INGESTION_PRODUCER_*`.
 * - `MSK_PRODUCER` — legacy MSK cluster. Default for everything the CDP used
 *   to send through the raw `KafkaProducerWrapper` (prefiltered events,
 *   precalculated person properties, legacy plugin app metrics, batch hogflow).
 * - `WAREHOUSE_PRODUCER` — dedicated cluster for warehouse source webhooks,
 *   configured via `KAFKA_WAREHOUSE_PRODUCER_*`.
 */
export function createCdpProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP)
        .register(MSK_PRODUCER, MSK_PRODUCER_CONFIG_MAP)
        .register(WAREHOUSE_PRODUCER, WAREHOUSE_PRODUCER_CONFIG_MAP)
}
