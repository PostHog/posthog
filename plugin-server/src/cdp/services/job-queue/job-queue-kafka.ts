/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */

import { Message } from 'node-rdkafka'
import { compress, uncompress } from 'snappy'

import { KafkaConsumer, parseKafkaHeaders } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { PluginsServerConfig } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import {
    HogFunctionInvocation,
    HogFunctionInvocationJobQueue,
    HogFunctionInvocationResult,
    HogFunctionInvocationSerialized,
} from '../../types'
import { HogFunctionManagerService } from '../hog-function-manager.service'
import { cdpJobSizeKb } from './shared'

export class CyclotronJobQueueKafka {
    private kafkaConsumer?: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper

    constructor(
        private config: PluginsServerConfig,
        private queue: HogFunctionInvocationJobQueue,
        private hogFunctionManager: HogFunctionManagerService,
        private consumeBatch: (invocations: HogFunctionInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
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
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic, callEachBatchWhenEmpty: true })

        logger.info('🔄', 'Connecting kafka consumer', { groupId, topic })
        await this.kafkaConsumer.connect(async (messages) => {
            const { backgroundTask } = await this.consumeKafkaBatch(messages)
            return { backgroundTask }
        })
    }

    public async stop() {
        await Promise.all([this.kafkaConsumer?.disconnect(), this.kafkaProducer?.disconnect()])
    }

    public isHealthy() {
        return this.kafkaConsumer!.isHealthy()
    }

    public async queueInvocations(invocations: HogFunctionInvocation[]) {
        if (invocations.length === 0) {
            return
        }

        const producer = this.getKafkaProducer()

        await Promise.all(
            invocations.map(async (x) => {
                const serialized = serializeHogFunctionInvocation(x)

                const value = this.config.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA
                    ? await compress(JSON.stringify(serialized))
                    : JSON.stringify(serialized)

                cdpJobSizeKb.observe(value.length / 1024)

                await producer
                    .produce({
                        value: Buffer.from(value),
                        key: Buffer.from(x.id),
                        topic: `cdp_cyclotron_${x.queue}`,
                        headers: {
                            hogFunctionId: x.hogFunction.id,
                            teamId: x.globals.project.id.toString(),
                        },
                    })
                    .catch((e) => {
                        logger.error('🔄', 'Error producing kafka message', {
                            error: String(e),
                            teamId: x.teamId,
                            hogFunctionId: x.hogFunction.id,
                            payloadSizeKb: value.length / 1024,
                            eventUrl: x.globals.event.url,
                        })

                        throw e
                    })
            })
        )
    }

    public async queueInvocationResults(invocationResults: HogFunctionInvocationResult[]) {
        // With kafka we are essentially re-queuing the work to the target topic if it isn't finished
        const invocations = invocationResults.reduce((acc, res) => {
            if (res.finished) {
                return acc
            }

            if (res.invocation.queue === 'fetch' && !res.invocation.queueParameters) {
                throw new Error('Fetch job has no queue parameters')
            }

            return [...acc, res.invocation]
        }, [] as HogFunctionInvocation[])

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
            return await this.consumeBatch([])
        }

        const invocations: HogFunctionInvocation[] = []
        const hogFunctionIds = new Set<string>()

        messages.forEach((message) => {
            const headers = parseKafkaHeaders(message.headers ?? [])
            const hogFunctionId = headers['hogFunctionId']
            if (hogFunctionId) {
                hogFunctionIds.add(hogFunctionId)
            }
        })

        const hogFunctions = await this.hogFunctionManager.getHogFunctions(Array.from(hogFunctionIds))

        // Parse all the messages into invocations
        for (const message of messages) {
            const rawValue = message.value
            if (!rawValue) {
                throw new Error('Bad message: ' + JSON.stringify(message))
            }

            // Try to decompress, otherwise just use the value as is
            const decompressedValue = await uncompress(rawValue).catch(() => rawValue)
            const invocationSerialized: HogFunctionInvocationSerialized = parseJSON(decompressedValue.toString())

            // NOTE: We might crash out here and thats fine as it would indicate that the schema changed
            // which we have full control over so shouldn't be possible
            const hogFunction = hogFunctions[invocationSerialized.hogFunctionId]

            if (!hogFunction) {
                logger.error('⚠️', 'Error finding hog function', {
                    id: invocationSerialized.hogFunctionId,
                })
                continue
            }

            const invocation: HogFunctionInvocation = {
                ...invocationSerialized,
                hogFunction,
                queueSource: 'kafka', // NOTE: We always set this here, as we know it came from kafka
            }

            invocations.push(invocation)
        }

        return await this.consumeBatch(invocations)
    }
}

export function serializeHogFunctionInvocation(invocation: HogFunctionInvocation): HogFunctionInvocationSerialized {
    const serializedInvocation: HogFunctionInvocationSerialized = {
        ...invocation,
        hogFunctionId: invocation.hogFunction.id,
    }

    delete (serializedInvocation as any).hogFunction

    return serializedInvocation
}
