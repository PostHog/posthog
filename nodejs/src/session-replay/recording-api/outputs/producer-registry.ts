import { WARPSTREAM_PRODUCER_CONFIG_MAP } from '../../../ingestion/common/config'
import { DEFAULT_PRODUCER, WARPSTREAM_PRODUCER } from '../../../ingestion/common/outputs'
import { KafkaProducerRegistryBuilder } from '../../../ingestion/outputs/kafka-producer-registry-builder'
import { SESSION_REPLAY_DEFAULT_PRODUCER_CONFIG_MAP } from '../../shared/outputs/producer-config'

/** Recording API only needs DEFAULT + WARPSTREAM producers. */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(DEFAULT_PRODUCER, SESSION_REPLAY_DEFAULT_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_PRODUCER, WARPSTREAM_PRODUCER_CONFIG_MAP)
}
