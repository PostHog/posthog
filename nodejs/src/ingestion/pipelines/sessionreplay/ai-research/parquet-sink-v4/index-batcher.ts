/**
 * Buffers v4 index rows across Kafka batches and writes one Parquet file per index and write day on each flush. Offsets
 * are stored only after every file that holds their rows is written, so a failed write replays (at-least-once). A flush
 * that succeeds then writes the watermark files of the partitions that this consumer still owns.
 */
import { Message, TopicPartition, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { logger } from '~/common/utils/logger'
import { OffsetStore } from '~/ingestion/pipelines/sessionreplay/shared/capture-watermark'

import { V4Index, V4IndexRow } from './index-columns'
import { parseIndexMessage } from './index-message'
import { WATERMARK_FILE_INTERVAL_MS } from './index-watermark-files'
import { V4ParquetSinkMetrics } from './metrics'

export type IndexFileStore = {
    encode(index: V4Index, rows: readonly V4IndexRow[]): Promise<Buffer>
    put(index: V4Index, writeDay: string, body: Buffer, nowMs: number): Promise<string>
}

export type IndexWatermarkWriter = {
    write(ownedOffsets: readonly TopicPartitionOffset[], nowMs: number): Promise<void>
    cancelWrites(partitions: readonly TopicPartition[]): void
}

export interface IndexBatcherOptions {
    flushIntervalMs: number
    maxRows: number
    maxBytes: number
    /** Called while a flush runs, so the health check does not restart a pod whose uploads are slow but bounded. */
    heartbeat?: () => void
    heartbeatIntervalMs?: number
}

const DEFAULT_HEARTBEAT_INTERVAL_MS = 10_000

interface BufferedRow {
    row: V4IndexRow
    partition: string
    bytes: number
}

interface IndexFileGroup {
    index: V4Index
    writeDay: string
    rows: BufferedRow[]
}

const partitionKey = (tp: TopicPartition): string => `${tp.topic}:${tp.partition}`

export class IndexBatcher {
    private groups = new Map<string, IndexFileGroup>()
    private rowCount = 0
    private bufferedBytes = 0
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private readonly storedOffsets = new Map<string, TopicPartitionOffset>()
    private lastWatermarkWriteMs: number | undefined
    /** Partitions revoked since their last message. A flush that started before the revocation must not store their offsets. */
    private readonly revoked = new Set<string>()
    private lastFlushMs: number
    private flushQueue: Promise<void> = Promise.resolve()

    constructor(
        private readonly store: IndexFileStore,
        private readonly offsetStore: OffsetStore,
        private readonly watermarkFiles: IndexWatermarkWriter,
        private readonly options: IndexBatcherOptions,
        nowMs: number
    ) {
        this.lastFlushMs = nowMs
    }

    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        for (const message of messages) {
            const partition = partitionKey(message)
            // A message proves the partition is assigned to this consumer again.
            this.revoked.delete(partition)
            const parsed = parseIndexMessage(message)
            if (parsed) {
                this.add(parsed.index, parsed.writeDay, {
                    row: parsed.row,
                    partition,
                    bytes: message.value?.length ?? 0,
                })
            }
        }
        for (const offset of findOffsetsToCommit(messages)) {
            this.pendingOffsets.set(partitionKey(offset), offset)
        }
        if (this.shouldFlush(nowMs)) {
            await this.flush(nowMs)
        } else if (this.watermarkFilesDue(nowMs)) {
            // A watermark can rise with no new rows, for example when its finished records expire, so idle polls rewrite the files too.
            await this.enqueue(() => this.writeWatermarkFilesIfDue(nowMs))
        }
    }

    /**
     * Drops the buffered rows and offsets of revoked partitions, and aborts their watermark writes. Their new owner reads
     * them again from the committed offset, so writing them here would only duplicate them, and this consumer can no
     * longer store their offsets.
     */
    public release(partitions: readonly TopicPartition[]): void {
        this.watermarkFiles.cancelWrites(partitions)
        const keys = new Set(partitions.map(partitionKey))
        let released = 0
        for (const key of keys) {
            this.revoked.add(key)
            this.pendingOffsets.delete(key)
            this.storedOffsets.delete(key)
        }
        for (const [groupKey, group] of this.groups) {
            const kept = group.rows.filter((buffered) => !keys.has(buffered.partition))
            for (const buffered of group.rows) {
                if (keys.has(buffered.partition)) {
                    released += 1
                    this.bufferedBytes -= buffered.bytes
                }
            }
            if (kept.length === 0) {
                this.groups.delete(groupKey)
            } else {
                group.rows = kept
            }
        }
        this.rowCount -= released
        V4ParquetSinkMetrics.incRowsReleased(released)
    }

    private add(index: V4Index, writeDay: string, buffered: BufferedRow): void {
        const key = `${index}/${writeDay}`
        const group = this.groups.get(key) ?? { index, writeDay, rows: [] }
        group.rows.push(buffered)
        this.groups.set(key, group)
        this.rowCount += 1
        this.bufferedBytes += buffered.bytes
    }

    private shouldFlush(nowMs: number): boolean {
        if (this.rowCount >= this.options.maxRows || this.bufferedBytes >= this.options.maxBytes) {
            return true
        }
        // Offsets of messages that gave no rows also flush on the interval, so they do not replay forever.
        const hasPending = this.rowCount > 0 || this.pendingOffsets.size > 0
        return hasPending && nowMs - this.lastFlushMs >= this.options.flushIntervalMs
    }

    public flush(nowMs: number): Promise<void> {
        return this.enqueue(() => this.flushNow(nowMs))
    }

    private enqueue(task: () => Promise<void>): Promise<void> {
        // A later flush's offsets also cover rows that an earlier flush is still writing, so flushes run one at a time and in order.
        const done = this.flushQueue.then(task)
        this.flushQueue = done.catch(() => undefined)
        return done
    }

    private watermarkFilesDue(nowMs: number): boolean {
        return (
            this.storedOffsets.size > 0 &&
            (this.lastWatermarkWriteMs === undefined || nowMs - this.lastWatermarkWriteMs >= WATERMARK_FILE_INTERVAL_MS)
        )
    }

    private async writeWatermarkFilesIfDue(nowMs: number): Promise<void> {
        if (!this.watermarkFilesDue(nowMs)) {
            return
        }
        this.lastWatermarkWriteMs = nowMs
        await this.watermarkFiles.write([...this.storedOffsets.values()], Date.now())
    }

    private async flushNow(nowMs: number): Promise<void> {
        const { heartbeat } = this.options
        // Each upload has its own timeout and encoding blocks the event loop, so this cannot hide a stalled flush.
        const heartbeats = heartbeat
            ? setInterval(heartbeat, this.options.heartbeatIntervalMs ?? DEFAULT_HEARTBEAT_INTERVAL_MS)
            : undefined
        heartbeats?.unref()
        try {
            await this.writeTaken(nowMs)
            await this.writeWatermarkFilesIfDue(nowMs)
        } finally {
            if (heartbeats) {
                clearInterval(heartbeats)
            }
        }
    }

    private async writeTaken(nowMs: number): Promise<void> {
        this.lastFlushMs = nowMs
        // The shutdown flush runs while the consumer loop still delivers batches, so a flush writes only what it takes here.
        const groups = this.groups
        const offsets = this.pendingOffsets
        this.groups = new Map()
        this.pendingOffsets = new Map()
        this.rowCount = 0
        this.bufferedBytes = 0
        const wroteFiles = groups.size > 0
        const unwritten = new Map(groups)
        try {
            for (const [groupKey, group] of groups) {
                const rows = group.rows.map((buffered) => buffered.row)
                let body: Buffer
                let key: string
                try {
                    body = await this.store.encode(group.index, rows)
                    key = await this.store.put(group.index, group.writeDay, body, Date.now())
                } catch (error) {
                    V4ParquetSinkMetrics.incWriteError()
                    throw error
                }
                unwritten.delete(groupKey)
                V4ParquetSinkMetrics.observeFile(group.index, rows.length, body.length)
                logger.info('🪶', 'ai_research_v4_parquet_index_written', {
                    key,
                    rows: rows.length,
                    bytes: body.length,
                })
            }
            const assigned = [...offsets].filter(([partition]) => !this.revoked.has(partition))
            if (assigned.length > 0) {
                this.offsetStore.offsetsStore(assigned.map(([, offset]) => offset))
                for (const [partition, offset] of assigned) {
                    this.storedOffsets.set(partition, offset)
                }
            }
            if (offsets.size > 0) {
                V4ParquetSinkMetrics.incFlush(wroteFiles ? 'written' : 'empty')
            }
        } catch (error) {
            for (const [groupKey, group] of unwritten) {
                const current = this.groups.get(groupKey)
                const rows = group.rows.filter((buffered) => !this.revoked.has(buffered.partition))
                if (current) {
                    current.rows = rows.concat(current.rows)
                } else if (rows.length > 0) {
                    this.groups.set(groupKey, { ...group, rows })
                }
                this.rowCount += rows.length
                this.bufferedBytes += rows.reduce((bytes, buffered) => bytes + buffered.bytes, 0)
            }
            for (const [partition, offset] of offsets) {
                // A newer offset for the partition stays, because the next flush stores it only after writing every row it covers.
                if (!this.pendingOffsets.has(partition) && !this.revoked.has(partition)) {
                    this.pendingOffsets.set(partition, offset)
                }
            }
            throw error
        }
    }
}
