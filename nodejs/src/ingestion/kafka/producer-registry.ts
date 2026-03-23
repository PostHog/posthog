import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { AllowedConfigKey, getProducerConfig } from './producer-config'

/**
 * Typed producer registry. Generic over `P` so the set of producers
 * is known at compile time.
 *
 * Each producer name maps to an env var config map via the configMaps constructor arg.
 * Safe for concurrent calls — caches the in-flight promise to prevent duplicate creation.
 */
export class KafkaProducerRegistry<P extends string> {
    private producers: Map<P, Promise<KafkaProducerWrapper>> = new Map()

    constructor(
        private kafkaClientRack: string | undefined,
        private configMaps: Record<P, Record<string, AllowedConfigKey>>
    ) {}

    /** Get or create a producer by its typed name. */
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
        logger.info('📝', `Creating producer "${name}"`, { config })
        return KafkaProducerWrapper.createWithConfig(this.kafkaClientRack, config)
    }

    /** Flush and disconnect all producers. Continues on failure to ensure all producers are attempted. */
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
