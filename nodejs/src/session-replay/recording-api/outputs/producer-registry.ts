import {
    INGESTION_SESSIONREPLAY_PRODUCER,
    INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP,
} from '@posthog/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'
import { KafkaProducerRegistryBuilder } from '@posthog/node-common/outputs/kafka-producer-registry-builder'

/** Recording API produces ClickHouse-bound deletion tombstones to the warpstream-replay cluster. */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack).register(
        INGESTION_SESSIONREPLAY_PRODUCER,
        INGESTION_SESSIONREPLAY_PRODUCER_CONFIG_MAP
    )
}
