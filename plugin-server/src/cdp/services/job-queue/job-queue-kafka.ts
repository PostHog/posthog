/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */

import { Message } from 'node-rdkafka'
import { compress, uncompress } from 'snappy'

import { KafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { PluginsServerConfig } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { cdpJobSizeKb } from './shared'

export class CyclotronJobQueueKafka {
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
        this.kafkaConsumer = new KafkaConsumer({ groupId, topic, callEachBatchWhenEmpty: true })

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

    public async queueInvocations(invocations: CyclotronJobInvocation[]) {
        if (invocations.length === 0) {
            return
        }

        const producer = this.getKafkaProducer()

        await Promise.all(
            invocations.map(async (x) => {
                const serialized = serializeInvocation(x)

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
                            // NOTE: Later we should remove hogFunctionId as it is no longer used
                            hogFunctionId: x.functionId,
                            functionId: x.functionId,
                            teamId: x.teamId.toString(),
                        },
                    })
                    .catch((e) => {
                        logger.error('🔄', 'Error producing kafka message', {
                            error: String(e),
                            teamId: x.teamId,
                            functionId: x.functionId,
                            payloadSizeKb: value.length / 1024,
                        })

                        throw e
                    })
            })
        )
    }

    public async queueInvocationResults(invocationResults: CyclotronJobInvocationResult[]) {
        // With kafka we are essentially re-queuing the work to the target topic if it isn't finished
        const invocations = invocationResults.reduce((acc, res) => {
            if (res.finished) {
                return acc
            }

            return [...acc, res.invocation]
        }, [] as CyclotronJobInvocation[])

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

        const invocations: CyclotronJobInvocation[] = []

        for (const message of messages) {
            const rawValue = message.value
            if (!rawValue) {
                throw new Error('Bad message: ' + JSON.stringify(message))
            }

            // Try to decompress, otherwise just use the value as is
            const decompressedValue = await uncompress(rawValue).catch(() => rawValue)
            const invocation: CyclotronJobInvocation = migrateKafkaCyclotronInvocation(
                parseJSON(decompressedValue.toString())
            )

            invocation.queueSource = 'kafka' // NOTE: We always set this here, as we know it came from kafka
            invocations.push(invocation)
        }

        return await this.consumeBatch(invocations)
    }
}

// NOTE: https://github.com/PostHog/posthog/pull/32588 modified the job format to move more things to the generic "state" value
// This function migrates any legacy jobs to the new format. We can remove this shortly after full release.
export function migrateKafkaCyclotronInvocation(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
    // Type casting but keeping as a reference
    const unknownInvocation = invocation as Record<string, any>

    if ('hogFunctionId' in unknownInvocation) {
        // Must be the old format
        unknownInvocation.functionId = unknownInvocation.hogFunctionId
        unknownInvocation.state = {}
        delete unknownInvocation.hogFunctionId

        if ('vmState' in unknownInvocation) {
            unknownInvocation.state.vmState = unknownInvocation.vmState
            delete unknownInvocation.vmState
        }
        if ('globals' in unknownInvocation) {
            unknownInvocation.state.globals = unknownInvocation.globals
            delete unknownInvocation.globals
        }
        if ('timings' in unknownInvocation) {
            unknownInvocation.state.timings = unknownInvocation.timings
            delete unknownInvocation.timings
        }
    }

    return invocation
}

export function serializeInvocation(invocation: CyclotronJobInvocation): CyclotronJobInvocation {
    // NOTE: We are copying the object to ensure it is clean of any spare params
    return {
        id: invocation.id,
        teamId: invocation.teamId,
        functionId: invocation.functionId,
        state: invocation.state,
        queue: invocation.queue,
        queueParameters: invocation.queueParameters,
        queuePriority: invocation.queuePriority,
        queueScheduledAt: invocation.queueScheduledAt,
        queueMetadata: invocation.queueMetadata,
        queueSource: invocation.queueSource,
    }
}
