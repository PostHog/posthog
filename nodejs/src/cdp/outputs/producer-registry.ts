import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    MSK_PRODUCER,
    MSK_PRODUCER_CONFIG_MAP,
    WARPSTREAM_INGESTION_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP,
} from './producers'

/**
 * Producers used by the CDP deployments.
 *
 * - `WARPSTREAM_INGESTION_PRODUCER` — current default for hog function
 *   monitoring (app metrics + log entries). Reads `KAFKA_MONITORING_PRODUCER_*`
 *   env vars which production already points at the warpstream-ingestion cluster.
 * - `MSK_PRODUCER` — alternate destination on the legacy MSK cluster.
 */
export function createCdpProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP)
        .register(MSK_PRODUCER, MSK_PRODUCER_CONFIG_MAP)
}
