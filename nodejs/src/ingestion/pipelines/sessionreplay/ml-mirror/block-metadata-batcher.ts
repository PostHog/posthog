/** Accumulates block-metadata across Kafka batches and flushes one Parquet object per time/row threshold. */
import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { parseJSON } from '~/common/utils/json-parse'

import { parseBlockMetadataMessages } from './block-metadata-message'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'
import { MlParquetSinkMetrics } from './metrics'
import { MlEncryptedEnvelope } from './privacy/crypto'
import { MlKafkaEncryption, ingestionVersion } from './privacy/transport'

/** The subset of the Kafka consumer the batcher needs: storing offsets it has durably written. */
export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

export interface BlockMetadataBatcherOptions {
    flushIntervalMs: number
    maxRows: number
    maxBytes?: number
}

export class BlockMetadataBatcher {
    private encrypted: MlEncryptedEnvelope[] = []
    private buffer: MlBlockMetadataRow[] = []
    private bufferedBytes = 0
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number

    constructor(
        private readonly store: BlockMetadataParquetStore,
        private readonly offsetStore: OffsetStore,
        private readonly options: BlockMetadataBatcherOptions,
        nowMs: number,
        private readonly privacy?: MlKafkaEncryption
    ) {
        this.lastFlushMs = nowMs
    }

    /** Buffers a batch and flushes once the buffer is old enough or large enough. */
    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        for (const message of messages) {
            this.bufferedBytes += message.value?.length ?? 0
        }
        const decoded = this.privacy
            ? await this.privacy.read(messages, 'metadata')
            : messages.map((message) => {
                  if (ingestionVersion(message) === 2) {
                      throw new Error('ML v2 metadata requires privacy configuration')
                  }
                  return { message, original: message, key: undefined, invalid: undefined }
              })
        MlParquetSinkMetrics.incRowsRejected('privacy', messages.length - decoded.length)
        let encryptedRows = 0
        for (const { original, key, invalid } of decoded) {
            if (invalid) {
                MlParquetSinkMetrics.incRowsRejected('invalid_envelope')
            }
            if (key) {
                this.encrypted.push(parseJSON(original.value!.toString()) as MlEncryptedEnvelope)
                encryptedRows++
            }
        }
        MlParquetSinkMetrics.incRowsParsed(encryptedRows)
        for (const row of parseBlockMetadataMessages(
            decoded.filter(({ key, invalid }) => !key && !invalid).map(({ message }) => message)
        )) {
            if (row.format_version !== 2) {
                this.buffer.push(row)
            }
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
        if (
            this.buffer.length + this.encrypted.length >= this.options.maxRows ||
            this.bufferedBytes >= (this.options.maxBytes ?? 32 * 1024 * 1024)
        ) {
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
        const wroteObject = this.buffer.length > 0 || this.encrypted.length > 0
        if (this.encrypted.length > 0) {
            await this.store.writeEncrypted(this.encrypted)
            this.encrypted = []
        }
        if (this.buffer.length > 0) {
            await this.store.write(this.buffer)
            this.buffer = []
        }
        this.bufferedBytes = 0
        if (this.pendingOffsets.size > 0) {
            // Commit after the write lands so a failed write replays; skipped-only batches still advance here.
            this.offsetStore.offsetsStore([...this.pendingOffsets.values()])
            this.pendingOffsets.clear()
            // 'empty' means we advanced past messages that produced no rows (all skipped/malformed): healthy
            // offset progress with zero Parquet output, the one state Kafka lag can't distinguish.
            MlParquetSinkMetrics.incFlush(wroteObject ? 'written' : 'empty')
        }
    }
}
