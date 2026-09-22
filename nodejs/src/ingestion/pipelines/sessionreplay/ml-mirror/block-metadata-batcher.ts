/** Accumulates block-metadata across Kafka batches and flushes one Parquet object per time/row threshold. */
import { Message, TopicPartitionOffset } from 'node-rdkafka'

import { findOffsetsToCommit } from '~/common/kafka/consumer/consumer-v1'
import { parseJSON } from '~/common/utils/json-parse'

import { isWellFormedRow, selectBlockMetadataFields } from './block-metadata-columns'
import { parseBlockMetadataMessages } from './block-metadata-message'
import { BlockMetadataParquetStore } from './block-metadata-parquet-store'
import { MlBlockMetadataRow } from './block-metadata-row'
import { MlEncryptedEnvelope, encryptEnvelopeJson } from './keys/crypto'
import { MlDecodedMessage, MlKafkaTransport, ingestionVersion } from './keys/transport'
import { MlParquetSinkMetrics } from './metrics'
import { EncryptedReplayIndex, encryptReplayIndex } from './replay-index'

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
    private encryptedIndex: EncryptedReplayIndex[] = []
    private buffer: MlBlockMetadataRow[] = []
    private bufferedBytes = 0
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number

    constructor(
        private readonly store: BlockMetadataParquetStore,
        private readonly offsetStore: OffsetStore,
        private readonly options: BlockMetadataBatcherOptions,
        nowMs: number,
        private readonly keyManager?: MlKafkaTransport
    ) {
        this.lastFlushMs = nowMs
    }

    /** Buffers a batch and flushes once the buffer is old enough or large enough. */
    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        for (const message of messages) {
            this.bufferedBytes += message.value?.length ?? 0
        }
        const decoded: MlDecodedMessage[] = this.keyManager
            ? await this.keyManager.read(messages, { sessionIdentity: rowSessionIdentity })
            : messages.map((message) => {
                  if (ingestionVersion(message) === 2) {
                      throw new Error('ML v2 metadata requires key manager configuration')
                  }
                  return { message, original: message, key: undefined, invalid: undefined }
              })
        MlParquetSinkMetrics.incRowsRejected('key_missing', messages.length - decoded.length)
        let encryptedRows = 0
        for (const { message, key, invalid, legacy } of decoded) {
            if (legacy) {
                continue
            }
            if (invalid) {
                MlParquetSinkMetrics.incRowsRejected('invalid_record')
            }
            if (key) {
                let row: unknown
                try {
                    row = parseJSON(message.value!.toString())
                } catch {
                    MlParquetSinkMetrics.incRowsRejected('parse_failed')
                    continue
                }
                if (isWellFormedRow(row)) {
                    const selected = selectBlockMetadataFields(row)
                    this.encrypted.push(encryptEnvelopeJson(key, 'metadata', Buffer.from(JSON.stringify(selected))))
                    encryptedRows++
                    const index = encryptReplayIndex(selected, key)
                    this.encryptedIndex.push(...index)
                    this.bufferedBytes += index.reduce((size, item) => size + JSON.stringify(item.envelope).length, 0)
                } else {
                    MlParquetSinkMetrics.incRowsRejected('invalid')
                }
            }
        }
        MlParquetSinkMetrics.incRowsParsed(encryptedRows)
        for (const row of parseBlockMetadataMessages(
            decoded.filter(({ key, invalid, legacy }) => !key && !invalid && !legacy).map(({ message }) => message)
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
        if (this.encryptedIndex.length > 0) {
            await this.store.writeEncryptedReplayIndex(this.encryptedIndex)
            this.encryptedIndex = []
        }
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

function rowSessionIdentity(message: Message): { teamId: number; sessionId: string } | null {
    let row: unknown
    try {
        row = parseJSON(message.value?.toString() ?? '')
    } catch {
        return null
    }
    if (!row || typeof row !== 'object' || !('session_id' in row) || !('team_id' in row)) {
        return null
    }
    const { session_id, team_id } = row as { session_id: unknown; team_id: unknown }
    if (typeof session_id !== 'string' || typeof team_id !== 'string' || !/^[0-9]+$/.test(team_id)) {
        return null
    }
    return { teamId: Number(team_id), sessionId: session_id }
}
