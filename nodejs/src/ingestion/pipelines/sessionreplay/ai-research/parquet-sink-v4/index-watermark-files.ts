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
 * While the sink makes progress, a file is at most this interval plus one flush interval old. Readers call a file older
 * than about 15 minutes stalled, so this interval and the flush interval must stay under that together.
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
    private readonly lastWrittenAtMs = new Map<string, number>()

    constructor(
        private readonly s3Client: S3Client,
        private readonly bucket: string,
        private readonly watermark: CaptureWatermark
    ) {}

    /**
     * `ownedOffsets` holds the last stored offset of each partition that the consumer still owns. Never throws, so a
     * failed write cannot fail the flush that called it. `filesBehind` is true when a failed write or the rewrite interval
     * kept the latest value out of a file.
     */
    public async write(
        ownedOffsets: readonly TopicPartitionOffset[],
        nowMs: number
    ): Promise<{ filesBehind: boolean }> {
        // Rows that are not in S3 yet hold the watermark down, because the batcher stores their offsets only after it writes them.
        const capturedAtMs = new Map<string, number>()
        for (const row of this.watermark.snapshot(nowMs)) {
            capturedAtMs.set(dataKey(row.topic, row.partition, row.data), row.capturedAtMs)
        }
        const writes: Promise<boolean>[] = []
        let skippedForInterval = false
        for (const { topic, partition, offset } of ownedOffsets) {
            for (const index of ['blocks', 'images'] as const) {
                const completeUpToCaptureMs = capturedAtMs.get(dataKey(topic, partition, INDEX_CAPTURED_DATA[index]))
                const key = watermarkFileKey(index, partition)
                const lastWrittenAtMs = this.lastWrittenAtMs.get(key)
                if (completeUpToCaptureMs === undefined) {
                    continue
                }
                if (lastWrittenAtMs !== undefined && nowMs - lastWrittenAtMs < WATERMARK_FILE_INTERVAL_MS) {
                    skippedForInterval = true
                    continue
                }
                writes.push(
                    this.put(index, key, nowMs, {
                        partition,
                        complete_up_to_capture_ms: completeUpToCaptureMs,
                        committed_offset: offset,
                        written_at_ms: nowMs,
                    })
                )
            }
        }
        const written = await Promise.all(writes)
        return { filesBehind: skippedForInterval || written.includes(false) }
    }

    private async put(index: V4Index, key: string, nowMs: number, file: IndexWatermarkFile): Promise<boolean> {
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
            return false
        }
        this.lastWrittenAtMs.set(key, nowMs)
        V4ParquetSinkMetrics.incWatermarkWrite(index, 'written')
        return true
    }
}
