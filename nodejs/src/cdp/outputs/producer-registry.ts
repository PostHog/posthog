import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import {
    WAREHOUSE_PRODUCER,
    WAREHOUSE_PRODUCER_CONFIG_MAP,
    WARPSTREAM_CALCULATED_EVENTS_PRODUCER,
    WARPSTREAM_CALCULATED_EVENTS_PRODUCER_CONFIG_MAP,
    WARPSTREAM_CYCLOTRON_PRODUCER,
    WARPSTREAM_CYCLOTRON_PRODUCER_CONFIG_MAP,
    WARPSTREAM_INGESTION_PRODUCER,
    WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP,
} from './producers'

/**
 * Producers used by the CDP deployments.
 *
 * - `WARPSTREAM_INGESTION_PRODUCER` — hog function monitoring (app metrics +
 *   log entries). Targets the warpstream-ingestion cluster.
 * - `WARPSTREAM_CALCULATED_EVENTS_PRODUCER` — dedicated cluster for the
 *   precalculated-filters consumer's outputs (`clickhouse_prefiltered_events`,
 *   `clickhouse_precalculated_person_properties`).
 * - `WARPSTREAM_CYCLOTRON_PRODUCER` — Cyclotron Warpstream cluster used for
 *   batch hogflow request enqueue. Distinct env-var prefix from the legacy
 *   `KAFKA_CDP_PRODUCER_*` so output routing is decoupled from the cyclotron
 *   job queue's own producer.
 * - `WAREHOUSE_PRODUCER` — dedicated cluster for warehouse source webhooks.
 */
export function createCdpProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_CALCULATED_EVENTS_PRODUCER, WARPSTREAM_CALCULATED_EVENTS_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_CYCLOTRON_PRODUCER, WARPSTREAM_CYCLOTRON_PRODUCER_CONFIG_MAP)
        .register(WAREHOUSE_PRODUCER, WAREHOUSE_PRODUCER_CONFIG_MAP)
}
