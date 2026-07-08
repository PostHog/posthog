/** Accumulates block-metadata across Kafka batches and flushes one Parquet object per time/row threshold. */
import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'

import { parseBlockMetadataMessages } from './block-metadata-message'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'

/** The subset of the Kafka consumer the batcher needs: storing offsets it has durably written. */
export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

export interface BlockMetadataBatcherOptions {
    flushIntervalMs: number
    maxRows: number
}

export class BlockMetadataBatcher {
    private buffer: MlBlockMetadataRow[] = []
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number

    constructor(
        private readonly store: BlockMetadataParquetStore,
        private readonly offsetStore: OffsetStore,
        private readonly options: BlockMetadataBatcherOptions,
        nowMs: number
    ) {
        this.lastFlushMs = nowMs
    }

    /** Buffers a batch and flushes once the buffer is old enough or large enough. */
    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        for (const row of parseBlockMetadataMessages(messages)) {
            this.buffer.push(row)
        }
        // Track the next offset to read per partition (highest seen + 1), accumulated across batches.
        for (const offset of findOffsetsToCommit(messages)) {
            this.pendingOffsets.set(`${offset.topic}:${offset.partition}`, offset)
        }
        if (this.shouldFlush(nowMs)) {
            await this.flush(nowMs)
        }
    }

    private shouldFlush(nowMs: number): boolean {
        if (this.buffer.length >= this.options.maxRows) {
            return true
        }
        // Flush on the interval whenever there's anything to commit — including offsets for batches that
        // produced no rows (all skipped/malformed), so those don't replay forever.
        const hasPending = this.buffer.length > 0 || this.pendingOffsets.size > 0
        return hasPending && nowMs - this.lastFlushMs >= this.options.flushIntervalMs
    }

    /**
     * Writes the buffered rows (if any) as one Parquet object, then stores the consumed offsets.
     * Throws (without storing offsets) if the write fails, so the consumer replays the window (at-least-once).
     */
    public async flush(nowMs: number): Promise<void> {
        this.lastFlushMs = nowMs
        if (this.buffer.length > 0) {
            await this.store.write(this.buffer)
            this.buffer = []
        }
        if (this.pendingOffsets.size > 0) {
            // Commit after the write lands so a failed write replays; skipped-only batches still advance here.
            this.offsetStore.offsetsStore([...this.pendingOffsets.values()])
            this.pendingOffsets.clear()
        }
    }
}
