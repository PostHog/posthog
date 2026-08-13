import { initializePrometheusLabels } from '~/common/api/router'
import { KAFKA_SESSION_REPLAY_IMAGE_FETCH } from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
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
 * One delay tier of the image fetch lane.
 *
 * The same server runs every tier. The topic and the period come from the environment, so three
 * deployments of one image cover 1 minute, 10 minutes, and one hour. See the lane's README.
 *
 * Two settings belong to the deployment rather than to this file:
 *
 * - `max.poll.interval.ms` must exceed the period of the topic. A consumer that sleeps longer than
 *   that value is evicted, and its partition is replayed by a consumer that will sleep just as long.
 * - One pod, and no more. A lag trigger assumes more consumers drain a topic faster, which is false
 *   here, because these records are waiting on purpose.
 */
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
        if (!topic) {
            throw new Error('SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_TOPIC must name the delay topic this pod drains')
        }

        this.producerRegistry = await createProducerRegistry(this.config.KAFKA_CLIENT_RACK).build(this.config)
        const producer = this.producerRegistry.getProducer(INGESTION_SESSIONREPLAY_ML_IMAGE_FETCH_PRODUCER)

        const consumerConfig: KafkaConsumerConfig = {
            topic,
            groupId: `${this.config.SESSION_RECORDING_ML_IMAGE_FETCH_GROUP_ID}-retry-${delayMs}`,
            autoCommit: true,
            autoOffsetStore: true,
            fetchBatchSize: this.config.SESSION_RECORDING_ML_IMAGE_FETCH_RETRY_BATCH_SIZE,
        }
        const consumer = new KafkaConsumer(consumerConfig)
        const delayConsumer = new RetryDelayConsumer(producer, {
            frontierTopic: KAFKA_SESSION_REPLAY_IMAGE_FETCH,
            delayMs,
            heartbeat: () => consumer.heartbeat(),
        })
        logger.info('🌐', 'ml_image_fetch_retry_started', { topic, delayMs })

        await consumer.connect((messages) => delayConsumer.handleBatch(messages))

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-fetch-retry',
            onShutdown: () => consumer.disconnect(),
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
