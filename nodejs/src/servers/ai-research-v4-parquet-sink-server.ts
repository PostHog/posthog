import { KAFKA_AI_RESEARCH_V4_INDEX } from '~/common/config/kafka-topics'
import { KafkaConsumer, KafkaConsumerConfig } from '~/common/kafka/consumer/consumer-v1'
import { logger } from '~/common/utils/logger'
import { AiResearchV4ServerConfig } from '~/ingestion/pipelines/sessionreplay/ai-research/config'
import { IndexBatcher } from '~/ingestion/pipelines/sessionreplay/ai-research/parquet-sink-v4/index-batcher'
import { indexCapturedData } from '~/ingestion/pipelines/sessionreplay/ai-research/parquet-sink-v4/index-message'
import { IndexParquetStore } from '~/ingestion/pipelines/sessionreplay/ai-research/parquet-sink-v4/index-parquet-store'
import { IndexWatermarkFiles } from '~/ingestion/pipelines/sessionreplay/ai-research/parquet-sink-v4/index-watermark-files'
import { AiResearchV4ConsumerServer } from '~/ingestion/pipelines/sessionreplay/ai-research/server/v4-consumer-server'
import {
    CaptureWatermark,
    capturedRecords,
    releasingOffsetStore,
} from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'
import { buildSessionRecordingS3Client } from '~/ingestion/pipelines/sessionreplay/shared/s3-client'

import { CleanupResources } from './base-server'

/** The v3 sink's default group. A v4 sink pod in it would take v3 partitions and read none of their topic. */
const V3_PARQUET_SINK_GROUP_ID = 'session-replay-ml-parquet-sink'

function assertOwnGroup(config: AiResearchV4ServerConfig): void {
    const group = config.AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID
    if (!group || group === V3_PARQUET_SINK_GROUP_ID) {
        throw new Error('AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID must be set and differ from the v3 sink group')
    }
}

/**
 * Manual offsets and callEachBatchWhenEmpty, as in the v3 sink: the batcher stores offsets only after their files are
 * written, and idle polls still reach the flush interval.
 */
export function buildV4SinkConsumerConfig(config: AiResearchV4ServerConfig): KafkaConsumerConfig {
    assertOwnGroup(config)
    return {
        topic: KAFKA_AI_RESEARCH_V4_INDEX,
        groupId: config.AI_RESEARCH_V4_PARQUET_SINK_GROUP_ID,
        autoCommit: true,
        autoOffsetStore: false,
        callEachBatchWhenEmpty: true,
    }
}

export class AiResearchV4ParquetSinkServer extends AiResearchV4ConsumerServer {
    protected async startServices(): Promise<void> {
        const consumerConfig = buildV4SinkConsumerConfig(this.config)
        const bucket = this.config.AI_RESEARCH_V4_RRWEB_BUCKET
        if (!bucket) {
            throw new Error('AI_RESEARCH_V4_RRWEB_BUCKET must be set for the v4 Parquet sink')
        }
        const rowGroupRows = this.config.AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS
        if (!Number.isInteger(rowGroupRows) || rowGroupRows <= 0) {
            throw new Error('AI_RESEARCH_V4_PARQUET_ROW_GROUP_ROWS must be a positive integer')
        }
        const s3Client = buildSessionRecordingS3Client(this.config)
        if (!s3Client) {
            throw new Error('SESSION_RECORDING_V2_S3_* must be configured for the v4 Parquet sink')
        }

        const consumer = new KafkaConsumer(consumerConfig)
        const watermark = new CaptureWatermark('ai_research_v4_parquet_sink')
        const batcher = new IndexBatcher(
            new IndexParquetStore(s3Client, bucket, rowGroupRows),
            releasingOffsetStore(consumer, watermark),
            new IndexWatermarkFiles(s3Client, bucket, watermark),
            {
                flushIntervalMs: this.config.AI_RESEARCH_V4_PARQUET_FLUSH_INTERVAL_MS,
                maxRows: this.config.AI_RESEARCH_V4_PARQUET_MAX_ROWS,
                maxBytes: this.config.AI_RESEARCH_V4_PARQUET_MAX_BYTES,
                heartbeat: () => consumer.reportDeliberateWait(),
            },
            Date.now()
        )
        await consumer.connect(
            (messages) => {
                consumer.heartbeat()
                watermark.hold(capturedRecords(messages, indexCapturedData))
                return batcher.handleBatch(messages, Date.now())
            },
            (partitions) => {
                batcher.release(partitions)
                watermark.forget(partitions)
                return Promise.resolve()
            }
        )

        this.lifecycle.services.push({
            id: 'ai-research-v4-parquet-sink',
            // Flush the buffer so a graceful restart does not read it again. A failed final flush replays on restart.
            onShutdown: async () => {
                try {
                    await batcher.flush(Date.now())
                } catch (error) {
                    logger.warn('🪶', 'ai_research_v4_parquet_sink_shutdown_flush_failed', { error: String(error) })
                }
                await consumer.disconnect()
            },
            healthcheck: () => consumer.isHealthy(),
        })
    }

    protected getCleanupResources(): CleanupResources {
        return { kafkaProducers: [], redisPools: [] }
    }
}
