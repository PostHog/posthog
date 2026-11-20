import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'

import {
    MSK_CDP_INTAKE_PRODUCER,
    MSK_CDP_INTAKE_PRODUCER_CONFIG_MAP,
    WAREHOUSE_PRODUCER,
    WAREHOUSE_PRODUCER_CONFIG_MAP,
    WARPSTREAM_CYCLOTRON_INTAKE_PRODUCER_CONFIG_MAP,
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
 * - `WARPSTREAM_CYCLOTRON_PRODUCER` — Cyclotron Warpstream cluster used for
 *   batch hogflow request enqueue. Distinct env-var prefix from the legacy
 *   `KAFKA_CDP_PRODUCER_*` so output routing is decoupled from the cyclotron
 *   job queue's own producer.
 * - `WAREHOUSE_PRODUCER` — dedicated cluster for warehouse source webhooks.
 * - `MSK_CDP_INTAKE_PRODUCER` — the intake topics on the CDP intake MSK cluster. It connects in the background, so a
 *   pod boots while that cluster is down. Without its brokers it opens the cyclotron producer's brokers, so local dev
 *   and hobby produce to their own Kafka.
 */
export function createCdpProducerRegistry(kafkaClientRack: string | undefined, mskIntakeBrokers: string) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(WARPSTREAM_INGESTION_PRODUCER, WARPSTREAM_INGESTION_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_CYCLOTRON_PRODUCER, WARPSTREAM_CYCLOTRON_PRODUCER_CONFIG_MAP)
        .register(WAREHOUSE_PRODUCER, WAREHOUSE_PRODUCER_CONFIG_MAP)
        .registerLazy(
            MSK_CDP_INTAKE_PRODUCER,
            mskIntakeBrokers ? MSK_CDP_INTAKE_PRODUCER_CONFIG_MAP : WARPSTREAM_CYCLOTRON_INTAKE_PRODUCER_CONFIG_MAP
        )
}
