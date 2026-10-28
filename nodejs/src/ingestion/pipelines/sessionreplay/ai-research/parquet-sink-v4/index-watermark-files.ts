/**
 * Writes `index/{index}/_watermarks/partition={NNNN}.json` to the rrweb bucket after a flush: the capture watermark of
 * one Kafka partition, so a reader of the bucket can see how far the index is complete without the metrics store.
 */
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { TopicPartitionOffset } from 'node-rdkafka'

import { logger } from '~/common/utils/logger'
import { CaptureWatermark, CapturedData } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'

import { V4Index } from './index-columns'
import { INDEX_CAPTURED_DATA } from './index-message'
import { V4ParquetSinkMetrics } from './metrics'

/**
 * The batcher rewrites the files on the first flush or poll after this interval, so a file of a running sink is at most
 * this interval plus one poll old. Readers call a file older than about 15 minutes stalled.
 */
export const WATERMARK_FILE_INTERVAL_MS = 3 * 60 * 1000
const WATERMARK_PUT_TIMEOUT_MS = 10_000

interface IndexWatermarkFile {
    partition: number
    complete_up_to_capture_ms: number
    committed_offset: number
    written_at_ms: number
}

function watermarkFileKey(index: V4Index, partition: number): string {
    return `index/${index}/_watermarks/partition=${String(partition).padStart(4, '0')}.json`
}

const dataKey = (topic: string, partition: number, data: CapturedData): string => `${topic}:${partition}:${data}`

export class IndexWatermarkFiles {
    constructor(
        private readonly s3Client: S3Client,
        private readonly bucket: string,
        private readonly watermark: CaptureWatermark
    ) {}

    /**
     * `ownedOffsets` holds the last stored offset of each partition that the consumer still owns. Never throws, so a
     * failed write cannot fail the flush that called it.
     */
    public async write(ownedOffsets: readonly TopicPartitionOffset[], nowMs: number): Promise<void> {
        // Rows that are not in S3 yet hold the watermark down, because the batcher stores their offsets only after it writes them.
        const capturedAtMs = new Map<string, number>()
        for (const row of this.watermark.snapshot(nowMs)) {
            capturedAtMs.set(dataKey(row.topic, row.partition, row.data), row.capturedAtMs)
        }
        const writes: Promise<void>[] = []
        for (const { topic, partition, offset } of ownedOffsets) {
            for (const index of ['blocks', 'images'] as const) {
                const completeUpToCaptureMs = capturedAtMs.get(dataKey(topic, partition, INDEX_CAPTURED_DATA[index]))
                if (completeUpToCaptureMs === undefined) {
                    continue
                }
                writes.push(
                    this.put(index, watermarkFileKey(index, partition), {
                        partition,
                        complete_up_to_capture_ms: completeUpToCaptureMs,
                        committed_offset: offset,
                        written_at_ms: nowMs,
                    })
                )
            }
        }
        await Promise.all(writes)
    }

    private async put(index: V4Index, key: string, file: IndexWatermarkFile): Promise<void> {
        try {
            await this.s3Client.send(
                new PutObjectCommand({
                    Bucket: this.bucket,
                    Key: key,
                    Body: JSON.stringify(file),
                    ContentType: 'application/json',
                }),
                { abortSignal: AbortSignal.timeout(WATERMARK_PUT_TIMEOUT_MS) }
            )
        } catch (error) {
            V4ParquetSinkMetrics.incWatermarkWrite(index, 'failed')
            logger.warn('🪶', 'ai_research_v4_parquet_watermark_write_failed', { key, error: String(error) })
            return
        }
        V4ParquetSinkMetrics.incWatermarkWrite(index, 'written')
    }
}
