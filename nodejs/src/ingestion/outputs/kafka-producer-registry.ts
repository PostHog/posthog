import { ProducerGlobalConfig } from 'node-rdkafka'

import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { AllowedConfigKey, getProducerConfig } from './kafka-producer-config'

const SENSITIVE_KEYS = new Set([
    'sasl.password',
    'sasl.oauthbearer.client.secret',
    'ssl.key.password',
    'ssl.key.pem',
    'ssl.certificate.pem',
])

function redactConfig(config: ProducerGlobalConfig): Record<string, unknown> {
    return Object.fromEntries(Object.entries(config).map(([k, v]) => [k, SENSITIVE_KEYS.has(k) ? '***' : v]))
}

/**
 * Typed producer registry that creates and caches Kafka producers by name.
 *
 * Generic over `P` so the set of valid producer names is known at compile time.
 * Each producer name maps to an env var config map via the `configMaps` constructor arg.
 * Safe for concurrent calls — caches the in-flight promise to prevent duplicate creation.
 *
 * @see `getProducerConfig()` for how env var maps are parsed into rdkafka config.
 */
export class KafkaProducerRegistry<P extends string> {
    private producers: Map<P, Promise<KafkaProducerWrapper>> = new Map()

    constructor(
        private kafkaClientRack: string | undefined,
        private configMaps: Record<P, Partial<Record<AllowedConfigKey, string>>>
    ) {}

    /**
     * Get or create a producer by its typed name.
     *
     * Returns a cached producer if one exists, otherwise creates it from the env var config map.
     *
     * @param name - The producer name to look up or create.
     */
    async getProducer(name: P): Promise<KafkaProducerWrapper> {
        const existing = this.producers.get(name)
        if (existing) {
            return existing
        }

        const promise = this.createProducer(name)
        this.producers.set(name, promise)
        return promise
    }

    private async createProducer(name: P): Promise<KafkaProducerWrapper> {
        const config = getProducerConfig(this.configMaps[name])
        logger.info('📝', `Creating producer "${name}"`, { config: redactConfig(config) })
        return KafkaProducerWrapper.createWithConfig(this.kafkaClientRack, config)
    }

    /**
     * Flush and disconnect all producers.
     *
     * Continues on failure to ensure all producers are attempted. Throws after all
     * disconnects complete if any failed.
     */
    async disconnectAll(): Promise<void> {
        const entries = Array.from(this.producers.entries())
        const errors: [string, unknown][] = []
        for (const [name, producerPromise] of entries) {
            logger.info('🔌', `Disconnecting producer "${name}"`)
            try {
                const producer = await producerPromise
                await producer.disconnect()
            } catch (err) {
                logger.error('🔌', `Failed to disconnect producer "${name}"`, { err })
                errors.push([name, err])
            }
        }
        this.producers.clear()
        if (errors.length > 0) {
            throw new Error(`Failed to disconnect producers: ${errors.map(([n]) => n).join(', ')}`)
        }
    }
}
