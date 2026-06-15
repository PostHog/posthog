/**
 * NOTE: We are often experimenting with different job queue implementations.
 * To make this easier this class is designed to abstract the queue as much as possible from
 * the underlying implementation.
 */
import { Message, MessageHeader } from 'node-rdkafka'
import { compress, uncompress } from 'snappy'

import { KafkaConsumerInterface, createKafkaConsumer } from '../../../kafka/consumer'
import { KafkaProducerWrapper } from '../../../kafka/producer'
import { HealthCheckResult, HealthCheckResultError } from '../../../types'
import { parseJSON } from '../../../utils/json-parse'
import { logger } from '../../../utils/logger'
import { CdpConfig } from '../../config'
import { CyclotronJobInvocation, CyclotronJobInvocationResult, CyclotronJobQueueKind } from '../../types'
import { JobQueue } from './job-queue.interface'
import {
    cdpCyclotronMessagesByEncoding,
    cdpJobSizeCompressedKb,
    cdpJobSizeKb,
    createInvocationSanitizer,
    observeConsumedBatch,
} from './shared'

const lz4: {
    encodeBound(size: number): number
    encodeBlock(input: Buffer, output: Buffer): number
    decodeBlock(input: Buffer, output: Buffer): number
} = require('lz4')

// LZ4 block payloads carry no length, so we prefix the 4-byte little-endian uncompressed size,
// matching the session replay envelope format. The 'content-encoding: lz4' header is what tells
// the consumer to use this path.
export function lz4CompressEnvelope(jsonString: string): Buffer {
    const input = Buffer.from(jsonString, 'utf8')
    const output = Buffer.allocUnsafe(lz4.encodeBound(input.length))
    const compressedSize = lz4.encodeBlock(input, output)
    const envelope = Buffer.allocUnsafe(4 + compressedSize)
    envelope.writeUInt32LE(input.length, 0)
    output.copy(envelope, 4, 0, compressedSize)
    return envelope
}

export function lz4DecompressEnvelope(buffer: Buffer): Buffer {
    const uncompressedSize = buffer.readUInt32LE(0)
    const output = Buffer.allocUnsafe(uncompressedSize)
    lz4.decodeBlock(buffer.subarray(4), output)
    return output
}

function getContentEncoding(headers: MessageHeader[] | undefined): string | null {
    if (!headers) {
        return null
    }
    for (const header of headers) {
        const value = header['content-encoding']
        if (value !== undefined) {
            return typeof value === 'string' ? value : value.toString()
        }
    }
    return null
}

export class CyclotronJobQueueKafka implements JobQueue {
    private kafkaConsumer?: KafkaConsumerInterface
    private kafkaProducer?: KafkaProducerWrapper
    private queue?: CyclotronJobQueueKind
    private consumeBatch?: (invocations: CyclotronJobInvocation[]) => Promise<{ backgroundTask: Promise<any> }>
    private sanitizer: ReturnType<typeof createInvocationSanitizer>

    constructor(
        private kafkaClientRack: string | undefined,
        private config: Pick<
            CdpConfig,
            | 'CDP_CYCLOTRON_COMPRESS_KAFKA_DATA'
            | 'CDP_CYCLOTRON_KAFKA_COMPRESSION_CODEC'
            | 'CDP_CYCLOTRON_STRIP_PERSON_FROM_STATE_TEAMS'
        >,
        private consumerBatchSize: number
    ) {
        this.sanitizer = createInvocationSanitizer(config)
    }

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
        const messages = this.sanitizer.sanitizeInvocations(invocations).map((x) => {
            const jsonString = JSON.stringify(serializeInvocation(x))
            cdpJobSizeKb.labels('kafka').observe(jsonString.length / 1024)

            return {
                jsonString,
                queue: x.queue,
                id: x.id,
                functionId: x.functionId,
                teamId: x.teamId,
            }
        })

        const useLz4 =
            this.config.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA &&
            this.config.CDP_CYCLOTRON_KAFKA_COMPRESSION_CODEC === 'lz4'

        await Promise.all(
            messages.map(async (msg) => {
                const headers: Record<string, string> = {
                    // NOTE: Later we should remove hogFunctionId as it is no longer used
                    hogFunctionId: msg.functionId,
                    functionId: msg.functionId,
                    teamId: msg.teamId.toString(),
                }

                let value: Buffer | string
                if (!this.config.CDP_CYCLOTRON_COMPRESS_KAFKA_DATA) {
                    value = msg.jsonString
                } else if (useLz4) {
                    value = lz4CompressEnvelope(msg.jsonString)
                    headers['content-encoding'] = 'lz4'
                } else {
                    value = await compress(msg.jsonString)
                }

                cdpJobSizeCompressedKb.labels('kafka').observe(value.length / 1024)

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

            // LZ4 payloads are tagged with a content-encoding header; everything else is either
            // snappy-compressed or raw JSON, so fall back to snappy-or-raw for those.
            let decompressedValue: Buffer
            let encoding: string
            if (getContentEncoding(message.headers) === 'lz4') {
                decompressedValue = lz4DecompressEnvelope(rawValue)
                encoding = 'lz4'
            } else {
                try {
                    decompressedValue = await uncompress(rawValue)
                    encoding = 'snappy'
                } catch {
                    decompressedValue = rawValue
                    encoding = 'none'
                }
            }
            cdpCyclotronMessagesByEncoding.labels(encoding).inc()
            const invocation: CyclotronJobInvocation = migrateKafkaCyclotronInvocation(
                parseJSON(decompressedValue.toString())
            )

            invocation.queueSource = 'kafka' // NOTE: We always set this here, as we know it came from kafka
            invocations.push(invocation)
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
