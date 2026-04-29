import { INGESTION_PRODUCER_CONFIG_MAP, WARPSTREAM_PRODUCER_CONFIG_MAP } from '../../ingestion/common/config'
import { DEFAULT_PRODUCER, INGESTION_PRODUCER, WARPSTREAM_PRODUCER } from '../../ingestion/common/outputs'
import { KafkaProducerRegistryBuilder } from '../../ingestion/outputs/kafka-producer-registry-builder'
import { SESSION_REPLAY_DEFAULT_PRODUCER_CONFIG_MAP } from '../../session-replay/shared/outputs/producer-config'

/**
 * Session replay needs DEFAULT, WARPSTREAM, and INGESTION producers.
 *
 * INGESTION targets the dedicated Kafka cluster between capture and ingestion —
 * suitable for DLQ and overflow topics that live alongside the input topic.
 */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(DEFAULT_PRODUCER, SESSION_REPLAY_DEFAULT_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_PRODUCER, WARPSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_PRODUCER, INGESTION_PRODUCER_CONFIG_MAP)
}
