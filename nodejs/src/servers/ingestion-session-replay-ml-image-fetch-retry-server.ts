import { LibrdKafkaError } from 'node-rdkafka'

import { initializePrometheusLabels } from '~/common/api/router'
import {
    KAFKA_SESSION_REPLAY_IMAGE_FETCH,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M,
} from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig, findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { KafkaProducerRegistry } from '~/common/outputs/kafka-producer-registry'
import { logger } from '~/common/utils/logger'
import { SessionReplayProducerName } from '~/ingestion/pipelines/sessionreplay/config'
import { RetryDelayConsumer } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-fetch/retry-delay-consumer'
import { createProducerRegistry } from '~/ingestion/pipelines/sessionreplay/outputs/producer-registry'
import { INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER } from '~/ingestion/pipelines/sessionreplay/shared/outputs/producer-config'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

/**
 * Headroom on top of the sleeping a batch can do, for the publishing between the sleeps.
 *
 * librdkafka rejects a `max.poll.interval.ms` above one day, so a tier and a batch size whose
 * product passes that is a configuration error rather than something to clamp silently.
 */
const POLL_INTERVAL_MARGIN_MS = 60_000
const MAX_POLL_INTERVAL_MS = 86_400_000
const REVOKED_PARTITION_CODES = new Set([-172, -190, -142, -144])

/** The topics the publisher writes to. A pod drains one of these and nothing else. */
const DELAY_TOPICS = [
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_10M,
    KAFKA_SESSION_REPLAY_IMAGE_FETCH_RETRY_1H,
]

export class IngestionSessionReplayMlImageFetchRetryServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayMlMirrorServerConfig
    private producerRegistry?: KafkaProducerRegistry<SessionReplayProducerName>

    constructor(config: Partial<IngestionSessionReplayMlMirrorServerConfig> = {}) {
        this.config = buildMlMirrorServerConfig(config)
        this.lifecycle = new ServerLifecycle(this.config)
    }

    async start(): Promise<void> {
        return this.lifecycle.start(
            () => this.startServices(),
            () => this.getCleanupResources()
        )
    }

    async stop(error?: Error): Promise<void> {
        return this.lifecycle.stop(() => this.getCleanupResources(), error)
    }

    private async startServices(): Promise<void> {
        initializePrometheusLabels(this.config.INGESTION_PIPELINE, this.config.INGESTION_LANE)

        const topic = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC
        const delayMs = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_DELAY_MS
        const batchSize = this.config.SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_BATCH_SIZE
        const producerDeliveryTimeoutMs = Number(
            this.config.KAFKA_INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER_MESSAGE_TIMEOUT_MS
        )
        // A typo here reads as an empty topic name, and librdkafka would subscribe to it and sit
        // idle while the tier filled. Naming the three the publisher writes to also stops a pod
        // draining the frontier itself, which has no period and would publish every record straight
        // back to it.
        if (!DELAY_TOPICS.includes(topic)) {
            throw new Error(
                `SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC must name one of ${DELAY_TOPICS.join(', ')}, got "${topic}"`
            )
        }
        if (!Number.isInteger(batchSize) || batchSize < 1) {
            throw new Error(`SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_BATCH_SIZE must be positive, got ${batchSize}`)
        }
        if (!Number.isFinite(producerDeliveryTimeoutMs) || producerDeliveryTimeoutMs <= 0) {
            throw new Error(`the image fetch retry producer needs a positive delivery timeout`)
        }

        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const producer = this.producerRegistry.getProducer(INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER)

        const consumerConfig: KafkaConsumerConfig = {
            topic,
            groupId: `${this.config.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID}-retry-${delayMs}`,
            autoCommit: true,
            // Stored after every publish in the batch is acknowledged.
            autoOffsetStore: false,
            fetchBatchSize: batchSize,
        }
        // Set here rather than left to the deployment. This consumer sleeps for the period of its
        // topic inside one batch, and the shared default of 300s would evict the 10m and 1h tiers
        // mid-sleep, then replay the partition into a consumer that sleeps just as long.
        //
        // The batch waits once for its latest broker append timestamp.
        const pollIntervalMs = delayMs + batchSize * producerDeliveryTimeoutMs + POLL_INTERVAL_MARGIN_MS
        if (pollIntervalMs > MAX_POLL_INTERVAL_MS) {
            throw new Error(
                `a delay of ${delayMs}ms and batch of ${batchSize} need a poll interval of ${pollIntervalMs}ms, which is past what Kafka allows`
            )
        }
        const consumer = new KafkaConsumer(consumerConfig, { 'max.poll.interval.ms': pollIntervalMs })
        // The shutdown handler sets this before it disconnects the consumer, so a stopping pod
        // abandons the wait it holds rather than making the rolling deploy wait out a tier period.
        let stopping = false
        const delayConsumer = new RetryDelayConsumer(producer, {
            isStopping: () => stopping,
            storeOffsets: (messages) => {
                try {
                    consumer.offsetsStore(findOffsetsToCommit(messages))
                } catch (error) {
                    const code = (error as LibrdKafkaError | undefined)?.code
                    if (!stopping && !REVOKED_PARTITION_CODES.has(code ?? 0)) {
                        throw error
                    }
                    logger.warn('🌐', 'ml_image_fetch_retry_offset_store_failed', {
                        partitions: messages.map((message) => message.partition),
                        code,
                        error: error instanceof Error ? error.name : 'unknown',
                    })
                }
            },
            frontierTopic: KAFKA_SESSION_REPLAY_IMAGE_FETCH,
            delayMs,
            heartbeat: () => consumer.reportDeliberateWait(),
        })
        logger.info('🌐', 'ml_image_fetch_retry_started', { topic, delayMs, pollIntervalMs })

        await consumer.connect((messages) => delayConsumer.handleBatch(messages))

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-fetch-retry',
            onShutdown: () => {
                stopping = true
                return consumer.disconnect()
            },
            healthcheck: () => consumer.isHealthy(),
        })
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
            additionalCleanup: () => this.producerRegistry?.disconnectAll(),
        }
    }
}
