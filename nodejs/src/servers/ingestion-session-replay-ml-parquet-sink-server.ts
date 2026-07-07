import { S3Client } from '@aws-sdk/client-s3'

import { initializePrometheusLabels } from '~/common/api/router'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { logger } from '~/common/utils/logger'
import { BlockMetadataBatcher } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-batcher'
import { BlockMetadataParquetStore } from '~/ingestion/pipelines/sessionreplay/ml-mirror/block-metadata-parquet-store'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { CleanupResources, NodeServer, ServerLifecycle } from './base-server'
import {
    IngestionSessionReplayMlMirrorServerConfig,
    buildMlMirrorServerConfig,
} from './ingestion-session-replay-ml-mirror-server'

/** The Parquet sink writes unencrypted data, so a misconfigured (absent) S3 client must fail loudly, not silently no-op. */
export function requireS3Client(client: S3Client | null): S3Client {
    if (!client) {
        throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the ML Parquet sink')
    }
    return client
}

/**
 * Manual offsets + callEachBatchWhenEmpty: the batcher rolls rows up across batches and stores offsets only after a
 * flush lands in S3, so a failed write replays the window (at-least-once) and idle polls still flush.
 */
export function buildSinkConsumerConfig(config: IngestionSessionReplayMlMirrorServerConfig): KafkaConsumerConfig {
    return {
        topic: config.INGESTION_SESSIONREPLAY_OUTPUT_ML_BLOCK_METADATA_TOPIC,
        groupId: config.SESSION_RECORDING_ML_PARQUET_SINK_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: false,
        callEachBatchWhenEmpty: true,
    }
}

/** Drains the ML block-metadata topic, rolling rows up into one Parquet object per flush interval in the ML bucket. */
export class IngestionSessionReplayMlParquetSinkServer implements NodeServer {
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
        const store = new BlockMetadataParquetStore(
            s3Client,
            this.config.SESSION_RECORDING_V2_S3_BUCKET,
            this.config.SESSION_RECORDING_ML_METADATA_PREFIX
        )

        const consumer = new KafkaConsumer(buildSinkConsumerConfig(this.config))
        const batcher = new BlockMetadataBatcher(
            store,
            consumer,
            {
                flushIntervalMs: this.config.SESSION_RECORDING_ML_PARQUET_FLUSH_INTERVAL_MS,
                maxRows: this.config.SESSION_RECORDING_ML_PARQUET_MAX_ROWS,
            },
            Date.now()
        )
        await consumer.connect((messages) => {
            consumer.heartbeat()
            return batcher.handleBatch(messages, Date.now())
        })

        this.lifecycle.services.push({
            id: 'session-replay-ml-parquet-sink',
            // Flush the buffer so a graceful restart doesn't re-process it, then disconnect.
            // A failed final flush is non-fatal (the window replays on restart) but must be visible.
            onShutdown: async () => {
                try {
                    await batcher.flush(Date.now())
                } catch (error) {
                    logger.warn('🪶', 'ml_parquet_sink_shutdown_flush_failed', { error: String(error) })
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
