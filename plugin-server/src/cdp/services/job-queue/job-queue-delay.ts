/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { DateTime } from 'luxon'
import { Message } from 'node-rdkafka'

import { KafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { PluginsServerConfig } from '../../../types'
import { logger } from '../../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobQueueKind } from '../../types'

export const getDelayQueue = (_queueScheduledAt: DateTime): CyclotronJobQueueKind => {
    // if (queueScheduledAt > DateTime.now().plus({ hours: 24 })) {
    //     return 'delay_24h'
    // }

    // if (queueScheduledAt > DateTime.now().plus({ minutes: 10 })) {
    //     return 'delay_60m'
    // }

    return 'delay_10m' // Force everything to the 10m queue for now
}

export const getDelayByQueue = (queue: CyclotronJobQueueKind): number => {
    switch (queue) {
        case 'delay_24h':
            return 24 * 60 * 60 * 1000 // 24 hours
        case 'delay_60m':
            return 60 * 60 * 1000 // 1 hour
        case 'delay_10m':
            return 10 * 60 * 1000 // 10 minutes
        default:
            throw new Error(`Invalid queue: ${queue}`)
    }
}

export class CyclotronJobQueueDelay {
    private kafkaConsumer?: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper
    protected name = 'CdpCyclotronDelayQueue'

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
        // Disable auto-commit for manual control over long-running batches
        this.kafkaConsumer = new KafkaConsumer({
            groupId,
            topic,
            callEachBatchWhenEmpty: true,
            autoCommit: true,
            autoOffsetStore: false,
        })

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

        logger.info('🔁', `${this.name} - Consuming batch`, { messageCount: messages.length })

        const maxDelayMs = getDelayByQueue(this.queue)

        for (const message of messages) {
            try {
                const returnTopic = this.getHeaderValue(message.headers, 'returnTopic') as CyclotronJobQueueKind
                const queueScheduledAt = this.getHeaderValue(message.headers, 'queueScheduledAt')

                if (!returnTopic || !queueScheduledAt) {
                    logger.warn('Missing required headers', {
                        returnTopic,
                        queueScheduledAt,
                        messageKey: message.key,
                    })
                    this.kafkaConsumer?.offsetsStore([
                        {
                            ...message,
                            offset: message.offset + 1,
                        },
                    ])
                    continue
                }

                const now = new Date().getTime()
                const scheduledTime = new Date(queueScheduledAt)
                let delayMs = Math.max(0, scheduledTime.getTime() - now)
                const waitTime = Math.min(delayMs, maxDelayMs)

                logger.info(
                    '🔁',
                    `${this.name} - Waiting for ${waitTime}ms before processing ${messages.indexOf(message) + 1}/${messages.length} invocation ${message.key}`
                )

                delayMs -= waitTime

                await new Promise((resolve) => setTimeout(resolve, waitTime))

                const producer = this.getKafkaProducer()

                await producer.produce({
                    value: message.value,
                    key: message.key as string,
                    topic:
                        delayMs === 0
                            ? returnTopic
                            : `cdp_cyclotron_${getDelayQueue(DateTime.fromMillis(scheduledTime.getTime() - waitTime))}`,
                    headers: message.headers as unknown as Record<string, string>,
                })

                const result = this.kafkaConsumer?.offsetsStore([
                    {
                        ...message,
                        offset: message.offset + 1,
                    },
                ])

                logger.info('🔁', `${this.name} - Successfully processed and committed message ${message.key}`, {
                    offset: message.offset,
                    result,
                })
            } catch (error) {
                const result = this.kafkaConsumer?.offsetsStore([
                    {
                        ...message,
                        offset: message.offset + 1,
                    },
                ])
                logger.info('🔁', `${this.name} - Error processing message ${message.key}`, {
                    offset: message.offset,
                    result,
                    error,
                })
                throw error
            }
        }

        logger.info('🔁', `${this.name} - Consumed full delay batch`, { messageCount: messages.length })

        return await this.consumeBatch([])
    }
}
