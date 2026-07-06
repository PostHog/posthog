import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { KafkaProducerRegistryBuilder } from '~/common/outputs/kafka-producer-registry-builder'

import {
    INGESTION_DOWNSTREAM_PRODUCER,
    INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP,
    INGESTION_UPSTREAM_PRODUCER,
    INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP,
    ProducerName,
} from './producers'

/**
 * The consolidated UPSTREAM/DOWNSTREAM producer slots, for the analytics-family servers
 * (general, error-tracking, ingestion-api). Each of these must wire both slots' brokers in
 * charts — an unconfigured slot falls through to the schema-default broker (`kafka:9092`),
 * which is reachable in dev/hobby but not in prod, so a missing wire fails fast there.
 * Session replay composes its own set instead.
 *
 * Lives in its own module (not producers.ts) so that importing the producer slot
 * names/maps — which config files do at module-eval time — does not transitively pull in
 * the Kafka producer machinery (and the logger → defaultConfig cycle behind it).
 */
export function createIngestionProducerRegistry(kafkaClientRack: string | undefined) {
    return new KafkaProducerRegistryBuilder(kafkaClientRack)
        .register(INGESTION_UPSTREAM_PRODUCER, INGESTION_UPSTREAM_PRODUCER_CONFIG_MAP)
        .register(INGESTION_DOWNSTREAM_PRODUCER, INGESTION_DOWNSTREAM_PRODUCER_CONFIG_MAP)
}

type ProducerRegistryConfig = Parameters<ReturnType<typeof createIngestionProducerRegistry>['build']>[0]

/**
 * Lifecycle owner for the shared Kafka producer registry. `start()`
 * connects all registered producers; `stop()` disconnects them.
 *
 * Builds the ingestion registry (the UPSTREAM/DOWNSTREAM slots), since its
 * only owners are the analytics-family servers and the client-warnings
 * consumer that runs under their scope.
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
