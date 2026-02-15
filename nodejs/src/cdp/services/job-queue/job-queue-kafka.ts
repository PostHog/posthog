/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { Message, KafkaConsumer as RdKafkaConsumer } from 'node-rdkafka'
import { hostname } from 'os'
import { Counter, Histogram } from 'prom-client'
import { compress, uncompress } from 'snappy'

import { getKafkaConfigFromEnv } from '../../../kafka/config'
import { KafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { HealthCheckResult, HealthCheckResultError, PluginsServerConfig } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { cdpJobSizeKb } from './shared'

export const cdpSeekLatencyMs = new Histogram({
    name: 'cdp_seek_latency_ms',
    help: 'Latency in ms of seeking back to a specific offset to re-read a message',
    buckets: [1, 5, 10, 25, 50, 100, 150, 200, 250, 500, 1000, 2500, 5000, 10000],
})

export const cdpSeekResult = new Counter({
    name: 'cdp_seek_result_total',
    help: 'Count of seek test results by outcome',
    labelNames: ['result'],
})

export class CyclotronJobQueueKafka {
    private kafkaConsumer?: KafkaConsumer
    private kafkaProducer?: KafkaProducerWrapper
    private seekTestConsumer?: RdKafkaConsumer

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
        this.kafkaProducer = await KafkaProducerWrapper.create(this.config.KAFKA_CLIENT_RACK, 'CDP_PRODUCER')
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

        // Initialize seek test consumer if enabled
        if (this.config.CDP_CYCLOTRON_TEST_SEEK_LATENCY) {
            try {
                this.seekTestConsumer = new RdKafkaConsumer(
                    {
                        'client.id': `${hostname()}-seek-test`,
                        'metadata.broker.list': this.config.KAFKA_HOSTS,
                        ...getKafkaConfigFromEnv('CONSUMER'),
                        // Static group.id is safe here: we only use assign() (not subscribe()),
                        // so no group coordination or rebalancing occurs across consumers.
                        'group.id': 'cdp-seek-test',
                        'enable.auto.commit': false,
                        'enable.auto.offset.store': false,
                    },
                    { 'auto.offset.reset': 'earliest' }
                )
                this.seekTestConsumer.setDefaultConsumeTimeout(5000)
                await new Promise((resolve, reject) =>
                    this.seekTestConsumer!.connect({}, (error, data) => (error ? reject(error) : resolve(data)))
                )
                logger.info('🔄', 'Seek test consumer connected')
            } catch (error) {
                logger.warn('🔄', 'Failed to initialize seek test consumer, seek tests will be skipped', {
                    error: String(error),
                })
                this.seekTestConsumer = undefined
            }
        }
    }

    public async stopConsumer() {
        await this.kafkaConsumer?.disconnect()

        if (this.seekTestConsumer) {
            await new Promise<void>((resolve) => {
                this.seekTestConsumer!.disconnect((error) => {
                    if (error) {
                        logger.warn('Failed to disconnect seek test consumer', { error })
                    }
                    resolve()
                })
            })
        }
    }

    public async stopProducer() {
        await this.kafkaProducer?.disconnect()
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

        await Promise.all(
            invocations.map(async (x) => {
                const serialized = serializeInvocation(x)

                const value = this.config.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA
                    ? await compress(JSON.stringify(serialized))
                    : JSON.stringify(serialized)

                cdpJobSizeKb.observe(value.length / 1024)

                const headers: Record<string, string> = {
                    // NOTE: Later we should remove hogFunctionId as it is no longer used
                    hogFunctionId: x.functionId,
                    functionId: x.functionId,
                    teamId: x.teamId.toString(),
                }

                if (x.queueScheduledAt && x.state?.returnTopic) {
                    headers.queueScheduledAt = x.queueScheduledAt.toString()
                    headers.returnTopic = `cdp_cyclotron_${x.state.returnTopic}`
                }

                await producer
                    .produce({
                        value: Buffer.from(value),
                        key: Buffer.from(x.id),
                        topic: `cdp_cyclotron_${x.queue}`,
                        headers,
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

        const result = await this.consumeBatch(invocations)

        // Seek-back latency test: for a sample of messages, seek to a random older offset
        // on the same partition and measure how long the read takes (for WarpStream evaluation).
        // Runs as background task so it doesn't block batch processing.
        if (this.seekTestConsumer) {
            const seekTestMessages = messages.filter(
                () => Math.random() < this.config.CDP_CYCLOTRON_TEST_SEEK_SAMPLE_RATE
            )

            if (seekTestMessages.length > 0) {
                const seekTestTask = (async () => {
                    for (const message of seekTestMessages) {
                        await this.testSeekLatency(message)
                    }
                })()

                return {
                    backgroundTask: Promise.all([result.backgroundTask, seekTestTask]),
                }
            }
        }

        return result
    }

    private async testSeekLatency(message: Message): Promise<void> {
        if (!this.seekTestConsumer) {
            return
        }

        const { topic, partition, offset } = message
        const maxSeekBack = Math.min(this.config.CDP_CYCLOTRON_TEST_SEEK_MAX_OFFSET, offset)
        if (maxSeekBack <= 0) {
            return
        }

        const seekBack = Math.floor(Math.random() * maxSeekBack) + 1
        const targetOffset = offset - seekBack

        try {
            this.seekTestConsumer.assign([{ topic, partition, offset: targetOffset }])

            const start = performance.now()

            const consumed = await new Promise<Message[]>((resolve, reject) => {
                this.seekTestConsumer!.consume(1, (error, messages) => (error ? reject(error) : resolve(messages)))
            })

            const latencyMs = performance.now() - start
            cdpSeekLatencyMs.observe(latencyMs)

            if (consumed.length > 0) {
                cdpSeekResult.labels({ result: 'success' }).inc()
                logger.info('seek_test', {
                    latencyMs: Math.round(latencyMs * 100) / 100,
                    partition,
                    currentOffset: offset,
                    targetOffset,
                    seekBack,
                    sizeBytes: consumed[0].value?.length,
                })
            } else {
                cdpSeekResult.labels({ result: 'empty' }).inc()
            }
        } catch (error) {
            cdpSeekResult.labels({ result: 'error' }).inc()
            logger.warn('seek_test_error', { error: String(error), topic, partition })
        }
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
        parentRunId: invocation.parentRunId,
        state: invocation.state,
        queue: invocation.queue,
        queueParameters: invocation.queueParameters,
        queuePriority: invocation.queuePriority,
        queueScheduledAt: invocation.queueScheduledAt,
        queueMetadata: invocation.queueMetadata,
        queueSource: invocation.queueSource,
    }
}
