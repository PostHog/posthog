import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { getNamedProducerConfig, hasNamedProducerConfig } from './named-producer-config'

const DEFAULT_KEY = '__DEFAULT__'

export class KafkaProducerRegistry {
    private producers: Map<string, Promise<KafkaProducerWrapper>> = new Map()

    constructor(private kafkaClientRack: string | undefined) {}

    /**
     * Get or create a producer (singleton per name).
     * Safe for concurrent calls — caches the in-flight promise to prevent duplicate creation.
     *
     * - `undefined` → default producer using the existing KAFKA_PRODUCER_* convention
     * - any string  → named producer from INGESTION_KAFKA_PRODUCER_{NAME}_* env vars (throws if unconfigured)
     */
    async getProducer(name: string | undefined): Promise<KafkaProducerWrapper> {
        const key = name === undefined ? DEFAULT_KEY : name.toUpperCase()

        const existing = this.producers.get(key)
        if (existing) {
            return existing
        }

        const promise = name === undefined ? this.createDefaultProducer() : this.createNamedProducer(key)
        this.producers.set(key, promise)
        return promise
    }

    private async createDefaultProducer(): Promise<KafkaProducerWrapper> {
        logger.info('📝', 'Creating default producer via KAFKA_PRODUCER_* config')
        return KafkaProducerWrapper.create(this.kafkaClientRack, 'PRODUCER')
    }

    private async createNamedProducer(normalizedName: string): Promise<KafkaProducerWrapper> {
        if (!hasNamedProducerConfig(normalizedName)) {
            throw new Error(
                `No INGESTION_KAFKA_PRODUCER_${normalizedName}_* env vars found. ` +
                    `Named producers must be explicitly configured via env vars.`
            )
        }

        const config = getNamedProducerConfig(normalizedName)
        logger.info('📝', `Creating named producer "${normalizedName}"`, { config })
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
