import { DEFAULT_PRODUCER_CONFIG_MAP } from '../../common/config'
import { DEFAULT_PRODUCER } from '../../common/outputs'
import { KafkaProducerRegistryBuilder } from '../../outputs/kafka-producer-registry-builder'

export type { DefaultProducerConfigKey } from '../../common/config'
export type { DefaultProducer, ProducerName } from '../../common/outputs'

export function registerProducers(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack).register(DEFAULT_PRODUCER, DEFAULT_PRODUCER_CONFIG_MAP)
}
