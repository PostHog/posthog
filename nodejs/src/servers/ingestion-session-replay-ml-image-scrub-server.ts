import { S3Client } from '@aws-sdk/client-s3'

import { initializePrometheusLabels } from '~/common/api/router'
import { KAFKA_SESSION_REPLAY_IMAGE_SCRUB } from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { logger } from '~/common/utils/logger'
import { ImageBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-batcher'
import { ImageShardStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-shard-store'
import { ScrubClient } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/scrub-client'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

/** Scrubbed images are written unencrypted to the ML bucket, so an absent S3 client must fail loudly. */
export function requireS3Client(client: S3Client | null): S3Client {
    if (!client) {
        throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the image-scrub consumer')
    }
    return client
}

/** Manual offsets + callEachBatchWhenEmpty: the batcher rolls images up across batches and stores offsets
 *  only after a shard lands in S3, so a failed write replays the window (at-least-once) and idle polls flush. */
export function buildImageScrubConsumerConfig(config: IngestionSessionReplayMlMirrorServerConfig): KafkaConsumerConfig {
    return {
        topic: KAFKA_SESSION_REPLAY_IMAGE_SCRUB,
        groupId: config.SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: false,
        callEachBatchWhenEmpty: true,
    }
}

/** Drains the image-scrub topic: scrubs each image via the sidecar, batches the results into shard objects + a content-hash parquet index in the ML bucket. */
export class IngestionSessionReplayMlImageScrubServer implements NodeServer {
    readonly lifecycle: ServerLifecycle
    private config: IngestionSessionReplayMlMirrorServerConfig

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

        const s3Client = requireS3Client(buildSessionRecordingS3Client(this.config))
        const store = new ImageShardStore(
            s3Client,
            this.config.SESSION_RECORDING_V2_S3_BUCKET,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX
        )
        const scrubClient = new ScrubClient(
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SIDECAR_URL,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_TIMEOUT_MS,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_RETRIES
        )

        const consumer = new KafkaConsumer(buildImageScrubConsumerConfig(this.config))
        const batcher = new ImageBatcher(
            store,
            consumer,
            scrubClient,
            {
                flushIntervalMs: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_FLUSH_INTERVAL_MS,
                maxImages: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_IMAGES,
                maxBytes: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BYTES,
                scrubConcurrency: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_SCRUB_CONCURRENCY,
                batchDeadlineMs: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_BATCH_DEADLINE_MS,
            },
            Date.now()
        )
        await consumer.connect((messages) => {
            consumer.heartbeat()
            return batcher.handleBatch(messages, Date.now())
        })

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-scrub',
            // Flush buffered images so a graceful restart doesn't re-process them, then disconnect.
            // A failed final flush is non-fatal (the window replays) but must be visible.
            onShutdown: async () => {
                try {
                    await batcher.flush(Date.now())
                } catch (error) {
                    logger.warn('🖼️', 'ml_image_scrub_shutdown_flush_failed', { error: String(error) })
                }
                await consumer.disconnect()
            },
            healthcheck: () => consumer.isHealthy(),
        })
    }

    private getCleanupResources(): CleanupResources {
        return {
            kafkaProducers: [],
            redisPools: [],
        }
    }
}
