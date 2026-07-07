import { S3Client } from '@aws-sdk/client-s3'

import { initializePrometheusLabels } from '~/common/api/router'
import { KAFKA_SESSION_REPLAY_IMAGE_SCRUB } from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { ImageBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-batcher'
import { ImageShardStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/image-shard-store'
import { ScrubClient } from '~/ingestion/pipelines/sessionreplay/ml-mirror-image-scrub/scrub-client'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

// A scrub + S3-write batch blocks the poll loop (which only heartbeats once per batch) for up to minutes, so
// we refresh the heartbeat this often during it. Must stay under CONSUMER_MAX_HEARTBEAT_INTERVAL_MS (30s).
const BATCH_HEARTBEAT_INTERVAL_MS = 10_000

export function requireS3Client(client: S3Client | null): S3Client {
    if (!client) {
        throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the image-scrub consumer')
    }
    return client
}

export function buildImageScrubConsumerConfig(config: IngestionSessionReplayMlMirrorServerConfig): KafkaConsumerConfig {
    return {
        topic: KAFKA_SESSION_REPLAY_IMAGE_SCRUB,
        groupId: config.SESSION_RECORDING_ML_IMAGE_SCRUB_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: false,
        callEachBatchWhenEmpty: true,
    }
}

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
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_PREFIX,
            this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_S3_WRITE_TIMEOUT_MS
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
                maxBatchScrubMs: this.config.SESSION_RECORDING_ML_IMAGE_SCRUB_MAX_BATCH_SCRUB_MS,
            },
            Date.now()
        )
        await consumer.connect((messages) => {
            const heartbeat = setInterval(() => consumer.heartbeat(), BATCH_HEARTBEAT_INTERVAL_MS)
            return batcher.handleBatch(messages, Date.now()).finally(() => clearInterval(heartbeat))
        })

        this.lifecycle.services.push({
            id: 'session-replay-ml-image-scrub',
            // disconnect() stops the poll loop and commits stored offsets. The un-flushed buffer's offsets were
            // never stored, so those messages just replay on restart — a final flush here would only race the
            // still-running loop over the shared buffer.
            onShutdown: () => consumer.disconnect(),
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
