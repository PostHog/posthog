/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { Message } from 'node-rdkafka'

import { KafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'

export class CyclotronJobQueueDelay {
    private kafkaConsumer?: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper

    constructor(
        private config: PluginsServerConfig,
        private queue: CyclotronJobQueueKind,
        private consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ) {}

    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        // NOTE: For producing we use different values dedicated for Cyclotron as this is typically using its own Kafka cluster
        this.kafkaProducer = await KafkaProducerWrapper.create(
            {
                ...this.config,
            },
            'CDP_PRODUCER'
        )
    }

    public async startAsConsumer() {
        const groupId = `cdp-cyclotron-${this.queue}-consumer`
        const topic = `cdp_cyclotron_${this.queue}`

        // NOTE: As there is only ever one consumer per process we use the KAFKA_CONSUMER_ vars as with any other consumer
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic, callEachBatchWhenEmpty: true, autoCommit: false })

        logger.info('🔄', 'Connecting kafka consumer', { groupId, topic })
        await this.kafkaConsumer.connect(async (messages) => {
            const { backgroundTask } = await this.consumeKafkaBatch(messages)
            return { backgroundTask }
        })
    }

    public async stopConsumer() {
        await this.kafkaConsumer?.disconnect()
    }

    public async stopProducer() {
        await this.kafkaProducer?.disconnect()
    }

    public isHealthy() {
        return this.kafkaConsumer?.isHealthy() ?? false
    }

    private getKafkaProducer(): KafkaProducerWrapper {
        if (!this.kafkaProducer) {
            throw new Error('KafkaProducer not initialized')
        }
        return this.kafkaProducer
    }

    private getHeaderValue(headers: any[] | undefined, key: string): string | undefined {
        if (!headers || !Array.isArray(headers)) {
            return undefined
        }
        
        for (const header of headers) {
            if (header[key]) {
                // Convert Uint8Array to string
                return Buffer.from(header[key]).toString('utf8')
            }
        }
        return undefined
    }

    private async consumeKafkaBatch(messages: Message[]): Promise<{ backgroundTask: Promise<any> }> {
        if (messages.length === 0) {
            return await this.consumeBatch([])
        }

        console.log('CdpCyclotronDelayConsumer', `Consuming batch ${messages.length}`)

        const now = new Date().getTime()
        const maxDelayMs = 10 * 60 * 1000// 10 minutes

        for (const message of messages) {
            const returnTopic = this.getHeaderValue(message.headers, 'returnTopic') as CyclotronJobQueueKind
            const queueScheduledAt = this.getHeaderValue(message.headers, 'queueScheduledAt')

            if (!returnTopic || !queueScheduledAt) {
                logger.warn('Missing required headers', { 
                    returnTopic, 
                    queueScheduledAt, 
                    messageKey: message.key 
                })
                continue
            }

            const scheduledTime = new Date(queueScheduledAt)
            let delayMs = Math.max(0, scheduledTime.getTime() - now)
            const waitTime = Math.min(delayMs, maxDelayMs)

            console.log('CdpCyclotronDelayConsumer', `Waiting for ${waitTime}ms before processing ${messages.indexOf(message) + 1}/${messages.length} invocation ${message.key}`)

            await new Promise((resolve) => setTimeout(resolve, waitTime))

            const producer = this.getKafkaProducer()

            await producer.produce({
                value: message.value,
                key: message.key as string,
                topic: returnTopic,
                headers: message.headers as unknown as Record<string, string>,
            })

            await this.kafkaConsumer?.offsetsStore([message])
        }

        console.log('CdpCyclotronDelayConsumer', 'Consumed full delay batch', messages.length)

        return await this.consumeBatch([])
    }
}