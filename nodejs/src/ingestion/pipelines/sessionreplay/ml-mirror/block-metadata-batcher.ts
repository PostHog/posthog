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
import { usesV3Dataset } from './session-identifier-format'

/** The subset of the Kafka consumer the batcher needs: storing offsets it has durably written. */
export interface OffsetStore {
    offsetsStore(offsets: TopicPartitionOffset[]): void
}

/** The subset of the ML Kafka transport the batcher needs: reading each record with its session key. */
export type KeyedRecordReader = Pick<MlKafkaTransport, 'read'>

export interface BlockMetadataBatcherOptions {
    flushIntervalMs: number
    maxRows: number
    maxBytes?: number
}

/** Bytes toward the byte limit for each buffer, so a failed flush puts back only the bytes of the buffers it puts back. */
interface BufferedBytes {
    plainV3: number
    encryptedIndex: number
    encrypted: number
    rows: number
}

const noBufferedBytes = (): BufferedBytes => ({ plainV3: 0, encryptedIndex: 0, encrypted: 0, rows: 0 })

const totalBytes = (bytes: BufferedBytes): number => bytes.plainV3 + bytes.encryptedIndex + bytes.encrypted + bytes.rows

export class BlockMetadataBatcher {
    private encrypted: MlEncryptedEnvelope[] = []
    private encryptedIndex: EncryptedReplayIndex[] = []
    private buffer: MlBlockMetadataRow[] = []
    private plainV3: MlBlockMetadataRow[] = []
    private bufferedBytes = noBufferedBytes()
    private pendingOffsets = new Map<string, TopicPartitionOffset>()
    private lastFlushMs: number
    private flushQueue: Promise<void> = Promise.resolve()

    constructor(
        private readonly store: BlockMetadataParquetStore,
        private readonly offsetStore: OffsetStore,
        private readonly options: BlockMetadataBatcherOptions,
        nowMs: number,
        private readonly keyManager?: KeyedRecordReader
    ) {
        this.lastFlushMs = nowMs
    }

    /** Buffers a batch and flushes once the buffer is old enough or large enough. */
    public async handleBatch(messages: Message[], nowMs: number): Promise<void> {
        const { plainV3Rows, plainV3Bytes, otherMessages } = splitPlainV3Rows(messages)
        const decoded: MlDecodedMessage[] = this.keyManager
            ? await this.keyManager.read(otherMessages, { sessionIdentity: rowSessionIdentity })
            : otherMessages.map((message) => {
                  if (ingestionVersion(message) === 2) {
                      throw new Error('ML v2 metadata requires key manager configuration')
                  }
                  return { message, original: message, key: undefined, invalid: undefined }
              })
        // Counted after the key read, so a flush that starts during the read cannot take these bytes without their rows.
        this.bufferedBytes.plainV3 += plainV3Bytes
        for (const { original, key } of decoded) {
            if (key) {
                this.bufferedBytes.encrypted += original.value?.length ?? 0
            } else {
                this.bufferedBytes.rows += original.value?.length ?? 0
            }
        }
        MlParquetSinkMetrics.incRowsRejected('key_missing', otherMessages.length - decoded.length)
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
                    this.bufferedBytes.encryptedIndex += index.reduce(
                        (size, item) => size + JSON.stringify(item.envelope).length,
                        0
                    )
                } else {
                    MlParquetSinkMetrics.incRowsRejected('invalid')
                }
            }
        }
        MlParquetSinkMetrics.incRowsParsed(encryptedRows + plainV3Rows.length)
        for (const row of parseBlockMetadataMessages(
            decoded.filter(({ key, invalid, legacy }) => !key && !invalid && !legacy).map(({ message }) => message)
        )) {
            if (row.format_version !== 2) {
                this.buffer.push(row)
            }
        }
        // No await separates this push from the offsets below, so a batch whose key read throws buffers no rows.
        this.plainV3.push(...plainV3Rows)
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
            this.buffer.length + this.encrypted.length + this.plainV3.length >= this.options.maxRows ||
            totalBytes(this.bufferedBytes) >= (this.options.maxBytes ?? 32 * 1024 * 1024)
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
    public flush(nowMs: number): Promise<void> {
        // A later flush's offsets also cover rows that an earlier flush is still writing, so flushes run one at a time and in order.
        const flushed = this.flushQueue.then(() => this.flushNow(nowMs))
        this.flushQueue = flushed.catch(() => undefined)
        return flushed
    }

    private async flushNow(nowMs: number): Promise<void> {
        this.lastFlushMs = nowMs
        // The shutdown flush runs while the consumer loop still delivers batches, so a flush writes only the rows it takes here and stores only their offsets.
        let plainV3 = this.plainV3
        let encryptedIndex = this.encryptedIndex
        let encrypted = this.encrypted
        let rows = this.buffer
        const offsets = this.pendingOffsets
        const bytes = this.bufferedBytes
        this.plainV3 = []
        this.encryptedIndex = []
        this.encrypted = []
        this.buffer = []
        this.pendingOffsets = new Map()
        this.bufferedBytes = noBufferedBytes()
        const wroteObject = rows.length > 0 || encrypted.length > 0 || plainV3.length > 0
        try {
            if (plainV3.length > 0) {
                await this.store.writePlainV3(plainV3)
                plainV3 = []
            }
            if (encryptedIndex.length > 0) {
                await this.store.writeEncryptedReplayIndex(encryptedIndex)
                encryptedIndex = []
            }
            if (encrypted.length > 0) {
                await this.store.writeEncrypted(encrypted)
                encrypted = []
            }
            if (rows.length > 0) {
                await this.store.write(rows)
                rows = []
            }
            if (offsets.size > 0) {
                // Commit after the write lands so a failed write replays; skipped-only batches still advance here.
                this.offsetStore.offsetsStore([...offsets.values()])
                // 'empty' means we advanced past messages that produced no rows (all skipped/malformed): healthy
                // offset progress with zero Parquet output, the one state Kafka lag can't distinguish.
                MlParquetSinkMetrics.incFlush(wroteObject ? 'written' : 'empty')
            }
        } catch (error) {
            if (plainV3.length > 0) {
                this.plainV3 = plainV3.concat(this.plainV3)
                this.bufferedBytes.plainV3 += bytes.plainV3
            }
            if (encryptedIndex.length > 0) {
                this.encryptedIndex = encryptedIndex.concat(this.encryptedIndex)
                this.bufferedBytes.encryptedIndex += bytes.encryptedIndex
            }
            if (encrypted.length > 0) {
                this.encrypted = encrypted.concat(this.encrypted)
                this.bufferedBytes.encrypted += bytes.encrypted
            }
            if (rows.length > 0) {
                this.buffer = rows.concat(this.buffer)
                this.bufferedBytes.rows += bytes.rows
            }
            for (const [partition, offset] of offsets) {
                // A newer offset for the partition stays, because the next flush stores it only after writing every row it covers.
                if (!this.pendingOffsets.has(partition)) {
                    this.pendingOffsets.set(partition, offset)
                }
            }
            throw error
        }
    }
}

/** A v3 session needs no session key, because the sink stores its metadata and replay index as plain Parquet. */
function splitPlainV3Rows(messages: Message[]): {
    plainV3Rows: MlBlockMetadataRow[]
    plainV3Bytes: number
    otherMessages: Message[]
} {
    const plainV3Rows: MlBlockMetadataRow[] = []
    let plainV3Bytes = 0
    const otherMessages: Message[] = []
    for (const message of messages) {
        const row = parsedV3Row(message)
        if (row === null) {
            otherMessages.push(message)
        } else if (isWellFormedRow(row) && row.format_version === 2) {
            plainV3Rows.push(selectBlockMetadataFields(row))
            plainV3Bytes += message.value?.length ?? 0
        } else {
            MlParquetSinkMetrics.incRowsRejected('invalid')
        }
    }
    return { plainV3Rows, plainV3Bytes, otherMessages }
}

function parsedV3Row(message: Message): object | null {
    let row: unknown
    try {
        if (ingestionVersion(message) !== 2) {
            return null
        }
        row = parseJSON(message.value?.toString() ?? '')
    } catch {
        return null
    }
    if (!row || typeof row !== 'object' || !('session_id' in row)) {
        return null
    }
    return typeof row.session_id === 'string' && usesV3Dataset(row.session_id) ? row : null
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
