import { DEFAULT_PRODUCER, INGESTION_PRODUCER, ProducerName, WARPSTREAM_PRODUCER } from '.'

import { KafkaProducerRegistry } from '../../outputs/kafka-producer-registry'
import { KafkaProducerRegistryBuilder } from '../../outputs/kafka-producer-registry-builder'
import { DEFAULT_PRODUCER_CONFIG_MAP, INGESTION_PRODUCER_CONFIG_MAP, WARPSTREAM_PRODUCER_CONFIG_MAP } from '../config'

/** Register all producers on the builder. Call `.build(config)` to resolve. */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(DEFAULT_PRODUCER, DEFAULT_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_PRODUCER, WARPSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_PRODUCER, INGESTION_PRODUCER_CONFIG_MAP)
}

type ProducerRegistryConfig = Parameters<ReturnType<typeof createProducerRegistry>['build']>[0]

/**
 * Lifecycle owner for the shared Kafka producer registry. `start()`
 * connects all registered producers; `stop()` disconnects them.
 */
export class KafkaProducerRegistryScope {
    constructor(
        private readonly kafkaClientRack: string | undefined,
        private readonly config: ProducerRegistryConfig
    ) {}

    async start(): Promise<{ value: KafkaProducerRegistry<ProducerName>; stop: () => Promise<void> }> {
        const registry = await createProducerRegistry(this.kafkaClientRack).build(this.config)
        return {
            value: registry,
            stop: () => registry.disconnectAll(),
        }
    }
}
