import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'

/**
 * Typed producer registry that holds pre-created Kafka producers by name.
 *
 * Generic over `P` so the set of valid producer names is known at compile time.
 * Producers are created by `KafkaProducerRegistryBuilder` and passed as a Record
 * to the constructor — the registry itself only manages access and shutdown.
 */
export class KafkaProducerRegistry<P extends string> {
    constructor(private producers: Record<P, KafkaProducerWrapper>) {}

    /**
     * Get a producer by its typed name.
     */
    getProducer(name: P): KafkaProducerWrapper {
        return this.producers[name]
    }

    /**
     * Flush and disconnect all producers.
     *
     * Continues on failure to ensure all producers are attempted. Throws after all
     * disconnects complete if any failed.
     */
    async disconnectAll(): Promise<void> {
        const entries = Object.entries<KafkaProducerWrapper>(this.producers)
        const errors: [string, unknown][] = []
        for (const [name, producer] of entries) {
            logger.info('🔌', `Disconnecting producer "${name}"`)
            try {
                await producer.disconnect()
            } catch (err) {
                logger.error('🔌', `Failed to disconnect producer "${name}"`, { err })
                errors.push([name, err])
            }
        }
        if (errors.length > 0) {
            throw new Error(`Failed to disconnect producers: ${errors.map(([n]) => n).join(', ')}`)
        }
    }
}
