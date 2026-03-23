import { KafkaProducerWrapper } from '../../kafka/producer'
import { logger } from '../../utils/logger'
import { getNamedProducerConfig, hasNamedProducerConfig } from './named-producer-config'

const DEFAULT_KEY = '__DEFAULT__'

export class KafkaProducerRegistry {
    private producers: Map<string, KafkaProducerWrapper> = new Map()

    constructor(private kafkaClientRack: string | undefined) {}

    /**
     * Get or create a producer (singleton per name).
     *
     * - `undefined` → default producer using the existing KAFKA_PRODUCER_* convention
     * - any string  → named producer from INGESTION_KAFKA_PRODUCER_{NAME}_* env vars (throws if unconfigured)
     */
    async getProducer(name: string | undefined): Promise<KafkaProducerWrapper> {
        if (name === undefined) {
            return this.getDefaultProducer()
        }

        const normalizedName = name.toUpperCase()
        const existing = this.producers.get(normalizedName)
        if (existing) {
            return existing
        }

        if (!hasNamedProducerConfig(normalizedName)) {
            throw new Error(
                `No INGESTION_KAFKA_PRODUCER_${normalizedName}_* env vars found. ` +
                    `Named producers must be explicitly configured via env vars.`
            )
        }

        const config = getNamedProducerConfig(normalizedName)
        logger.info('📝', `Creating named producer "${normalizedName}"`, { config })
        const producer = await KafkaProducerWrapper.createWithConfig(this.kafkaClientRack, config)
        this.producers.set(normalizedName, producer)
        return producer
    }

    private async getDefaultProducer(): Promise<KafkaProducerWrapper> {
        const existing = this.producers.get(DEFAULT_KEY)
        if (existing) {
            return existing
        }

        logger.info('📝', 'Creating default producer via KAFKA_PRODUCER_* config')
        const producer = await KafkaProducerWrapper.create(this.kafkaClientRack, 'PRODUCER')
        this.producers.set(DEFAULT_KEY, producer)
        return producer
    }

    /** Flush and disconnect all producers. */
    async disconnectAll(): Promise<void> {
        const entries = Array.from(this.producers.entries())
        for (const [name, producer] of entries) {
            logger.info('🔌', `Disconnecting producer "${name}"`)
            await producer.disconnect()
        }
        this.producers.clear()
    }
}
