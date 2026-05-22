/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { Message } from 'node-rdkafka'
import { compress, uncompress } from 'snappy'

import { KafkaConsumerInterface, createKafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { HealthCheckResult, HealthCheckResultError } from '../../../types'
import { logger } from '../../../utils/logger'
import { CdpConfig } from '../../config'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { CyclotronJobSerializer, cdpJobSizeCompressedKb, cdpJobSizeKb } from './cyclotron-job-serializer'
import { JobQueue } from './job-queue.interface'
import { observeConsumedBatch } from './shared'

export class CyclotronJobQueueKafka implements JobQueue {
    private kafkaConsumer?: KafkaConsumerInterface
    private kafkaProducer?: KafkaProducerWrapper
    private queue?: CyclotronJobQueueKind
    private consumeBatch?: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    private serializer = new CyclotronJobSerializer()

    constructor(
        private kafkaClientRack: string | undefined,
        private config: Pick<CdpConfig, 'CDP_CYCLOTRON_COMPRESS_KAFKA_DATA'>,
        private consumerBatchSize: number
    ) {}

    /**
     * Helper to only start the producer related code (e.g. when not a consumer)
     */
    public async startAsProducer() {
        if (this.kafkaProducer) {
            return
        }
        this.kafkaProducer = await KafkaProducerWrapper.create(this.kafkaClientRack, 'CDP_PRODUCER')
    }

    public async startAsConsumer(
        queue: CyclotronJobQueueKind,
        consumeBatch: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    ) {
        this.queue = queue
        this.consumeBatch = consumeBatch

        const groupId = `cdp-cyclotron-${this.queue}-consumer`
        const topic = `cdp_cyclotron_${this.queue}`

        // NOTE: As there is only ever one consumer per process we use the KAFKA_CONSUMER_ vars as with any other consumer
        this.kafkaConsumer = createKafkaConsumer({ groupId, topic, callEachBatchWhenEmpty: true })

        logger.info('🔄', 'Connecting kafka consumer', { groupId, topic })
        await this.kafkaConsumer.connect(async (messages) => {
            const { backgroundTask } = await this.consumeKafkaBatch(messages)
            return { backgroundTask }
        })
    }

    public async stopConsumer() {
        await this.kafkaConsumer?.disconnect()
        this.kafkaConsumer = undefined
    }

    public async stopProducer() {
        await this.kafkaProducer?.disconnect()
        this.kafkaProducer = undefined
    }

    public isHealthy(): HealthCheckResult {
        if (!this.kafkaConsumer) {
            return new HealthCheckResultError('Kafka consumer not initialized', {})
        }
        return this.kafkaConsumer.isHealthy()
    }

    public async queueInvocations(invocations: CyclotronJobInvocation[]) {
        if (invocations.length === 0) {
            return
        }

        const producer = this.getKafkaProducer()

        // Pre-serialize all messages eagerly so the produce closures below only
        // capture lightweight strings instead of full invocation objects (globals, vmState, etc.)
        const messages = invocations.map((x) => {
            const jsonString = this.serializer.serializeForKafka(x)
            cdpJobSizeKb.labels('kafka').observe(jsonString.length / 1024)

            return {
                jsonString,
                queue: x.queue,
                id: x.id,
                functionId: x.functionId,
                teamId: x.teamId,
            }
        })

        await Promise.all(
            messages.map(async (msg) => {
                const value = this.config.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA
                    ? await compress(msg.jsonString)
                    : msg.jsonString

                cdpJobSizeCompressedKb.labels('kafka').observe(value.length / 1024)

                const headers: Record<string, string> = {
                    // NOTE: Later we should remove hogFunctionId as it is no longer used
                    hogFunctionId: msg.functionId,
                    functionId: msg.functionId,
                    teamId: msg.teamId.toString(),
                }

                await producer
                    .produce({
                        value: Buffer.from(value),
                        key: Buffer.from(msg.id),
                        topic: `cdp_cyclotron_${msg.queue}`,
                        headers,
                    })
                    .catch((e) => {
                        logger.error('🔄', 'Error producing kafka message', {
                            error: String(e),
                            teamId: msg.teamId,
                            functionId: msg.functionId,
                            payloadSizeKb: value.length / 1024,
                        })

                        throw e
                    })
            })
        )
    }

    // Kafka jobs don't need explicit dequeue/cancel — they're just dropped
    public async dequeueInvocations(_invocations: CyclotronJobInvocation[]): Promise<void> {}
    public async cancelInvocations(_invocations: CyclotronJobInvocation[]): Promise<void> {}

    public async queueInvocationResults(invocationResults: CyclotronJobInvocationResult[]) {
        // With kafka we are essentially re-queuing the work to the target topic if it isn't finished
        const invocations: CyclotronJobInvocation[] = []
        for (const res of invocationResults) {
            if (!res.finished) {
                invocations.push(res.invocation)
            }
        }

        await this.queueInvocations(invocations)
    }

    private getKafkaProducer(): KafkaProducerWrapper {
        if (!this.kafkaProducer) {
            throw new Error('KafkaProducer not initialized')
        }
        return this.kafkaProducer
    }

    private async consumeKafkaBatch(messages: Message[]): Promise<{ backgroundTask: Promise<any> }> {
        if (messages.length === 0) {
            observeConsumedBatch({
                queue: this.queue!,
                source: 'kafka',
                batchSize: 0,
                maxBatchSize: this.consumerBatchSize,
            })
            return await this.consumeBatch!([])
        }

        const invocations: CyclotronJobInvocation[] = []

        for (const message of messages) {
            const rawValue = message.value
            if (!rawValue) {
                throw new Error('Bad message: ' + JSON.stringify(message))
            }

            // Try to decompress, otherwise just use the value as is
            const decompressedValue = await uncompress(rawValue).catch(() => rawValue)
            invocations.push(this.serializer.deserializeFromKafka(decompressedValue))
        }

        observeConsumedBatch({
            queue: this.queue!,
            source: 'kafka',
            batchSize: invocations.length,
            maxBatchSize: this.consumerBatchSize,
        })

        return await this.consumeBatch!(invocations)
    }
}
