import { DEFAULT_PRODUCER, WARPSTREAM_PRODUCER } from '.'

import { KafkaProducerRegistryBuilder } from '../../outputs/kafka-producer-registry-builder'
import { DEFAULT_PRODUCER_CONFIG_MAP, WARPSTREAM_PRODUCER_CONFIG_MAP } from '../config'

/** Register all producers on the builder. Call `.build(config)` to resolve. */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(DEFAULT_PRODUCER, DEFAULT_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_PRODUCER, WARPSTREAM_PRODUCER_CONFIG_MAP)
}
