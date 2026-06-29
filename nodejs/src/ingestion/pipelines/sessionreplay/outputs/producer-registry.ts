import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'
import { INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP } from '~/ingestion/common/producers'
import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

/**
 * Session replay's producer slots: DOWNSTREAM (warpstream-ingestion) for ClickHouse-bound
 * outputs, and SESSIONREPLAY (warpstream-replay) for replay-domain topics including their DLQ
 * and overflow. Replay does not use UPSTREAM.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_SESSIONREPLAY_PRODUCER, INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP)
}
