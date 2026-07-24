import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'
import {
    INGESTION_DOWNSTREAM_PRODUCER,
    INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP,
} from '~/ingestion/common/outputs/producers'
import {
    INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER,
    INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_CONFIG_MAP,
    INGESTION_SESSIONREPLAY_PRODUCER,
    INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

/**
 * Session replay's producer slots: DOWNSTREAM (warpstream-ingestion) for ClickHouse-bound
 * outputs, SESSIONREPLAY (warpstream-replay) for replay-domain topics including their DLQ
 * and overflow, and ML_IMAGE_SCRUB (same replay cluster, dedicated client) so the image
 * lane's heavy best-effort payloads cannot fill the SESSIONREPLAY queue and starve the
 * critical outputs. Replay does not use UPSTREAM.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_SESSIONREPLAY_PRODUCER, INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP)
        .register(
            INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER,
            INGESTION_SESSIONREPLAY_ML_IMAGE_SCRUB_PRODUCER_CONFIG_MAP
        )
}
