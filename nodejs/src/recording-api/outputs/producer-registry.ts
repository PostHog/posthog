import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'
import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP,
} from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

/** Recording API produces ClickHouse-bound deletion tombstones to the warpstream-replay cluster. */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack).register(
        INGESTION_SESSIONREPLAY_PRODUCER,
        INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP
    )
}
