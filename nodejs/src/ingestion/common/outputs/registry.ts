import {
    DEFAULT_PRODUCER,
    INGESTION_DOWNSTREAM_PRODUCER,
    INGESTION_PRODUCER,
    INGESTION_UPSTREAM_PRODUCER,
    ProducerName,
    WARPSTREAM_PRODUCER,
} from '.'

import { KafkaProducerRegistry } from '../../outputs/kafka-producer-registry'
import { KafkaProducerRegistryBuilder } from '../../outputs/kafka-producer-registry-builder'
import {
    DEFAULT_PRODUCER_CONFIG_MAP,
    INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP,
    INGESTION_PRODUCER_CONFIG_MAP,
    INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP,
    WARPSTREAM_PRODUCER_CONFIG_MAP,
} from '../config'

/** Register the legacy producer slots on the builder. Call `.build(config)` to resolve. */
export function createProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(DEFAULT_PRODUCER, DEFAULT_PRODUCER_CONFIG_MAP)
        .register(WARPSTREAM_PRODUCER, WARPSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_PRODUCER, INGESTION_PRODUCER_CONFIG_MAP)
}

/**
 * Legacy slots plus the consolidated UPSTREAM/DOWNSTREAM slots, for the analytics-family
 * servers (general, error-tracking, ingestion-api). Each of these must wire both new slots'
 * brokers in charts — an unconfigured slot connects to the schema-default broker and crashes,
 * which is the intended fail-fast signal. Session replay composes its own set instead.
 */
export function createIngestionProducerRegistry(kafkaClientRack: string | undefined) {
    return createProducerRegistry(kafkaClientRack)
        .register(INGESTION_UPSTREAM_PRODUCER, INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
}

type ProducerRegistryConfig = Parameters<ReturnType<typeof createIngestionProducerRegistry>['build']>[0]

/**
 * Lifecycle owner for the shared Kafka producer registry. `start()`
 * connects all registered producers; `stop()` disconnects them.
 *
 * Builds the ingestion registry (legacy slots plus the consolidated
 * UPSTREAM/DOWNSTREAM slots), since its only owners are the analytics-family
 * servers and the client-warnings consumer that runs under their scope.
 */
export class KafkaProducerRegistryComponent {
    constructor(
        private readonly kafkaClientRack: string | undefined,
        private readonly config: ProducerRegistryConfig
    ) {}

    async start(): Promise<{ value: KafkaProducerRegistry<ProducerName>; stop: () => Promise<void> }> {
        const registry = await createIngestionProducerRegistry(this.kafkaClientRack).build(this.config)
        return {
            value: registry,
            stop: () => registry.disconnectAll(),
        }
    }
}
