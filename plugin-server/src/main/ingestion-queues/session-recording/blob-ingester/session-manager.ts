import { Upload } from '@aws-sdk/lib-storage'
import { captureException, captureMessage } from '@sentry/node'
import { randomUUID } from 'crypto'
import { createReadStream, writeFileSync } from 'fs'
import { appendFile, unlink } from 'fs/promises'
import { DateTime } from 'luxon'
import path from 'path'
import { Counter, Gauge } from 'prom-client'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { ObjectStorage } from '../../../services/object_storage'
import { bufferFileDir } from '../session-recordings-blob-consumer'
import { PendingChunks } from './pending-chunks'
import { SessionOffsetHighWaterMark } from './session-offset-high-water-mark'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage } from './utils'

export const counterS3FilesWritten = new Counter({
    name: 'recording_s3_files_written',
    help: 'A single file flushed to S3',
    labelNames: ['flushReason'],
})

export const counterS3WriteErrored = new Counter({
    name: 'recording_s3_write_errored',
    help: 'Indicates that we failed to flush to S3 without recovering',
})

export const gaugeS3FilesBytesWritten = new Gauge({
    name: 'recording_s3_bytes_written',
    help: 'Number of bytes flushed to S3, not strictly accurate as we gzip while uploading',
    labelNames: ['team'],
})

export const gaugeS3LinesWritten = new Gauge({
    name: 'recording_s3_lines_written',
    help: 'Number of lines flushed to S3, which will let us see the human size of blobs - a good way to see how effective bundling is',
})

export const gaugePendingChunksDropped = new Gauge({
    name: 'recording_pending_chunks_dropped',
    help: `Chunks can be duplicated or arrive as expected.
        When flushing we need to check whether we have all chunks or should drop them.
        This metric indicates a set of pending chunks were incomplete for too long,
        were blocking ingestion, and were dropped`,
})

const ESTIMATED_GZIP_COMPRESSION_RATIO = 0.1

interface EventsRange {
    firstTimestamp: number
    lastTimestamp: number
}

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    oldestKafkaTimestamp: number | null
    count: number
    size: number
    file: string
    offsets: number[]
    eventsRange: EventsRange | null
}

export class SessionManager {
    chunks: Map<string, PendingChunks> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer
    destroying = false
    inProgressUpload: Upload | null = null
    lastProcessedOffset: number | null = null

    constructor(
        public readonly serverConfig: PluginsServerConfig,
        public readonly s3Client: ObjectStorage['s3'],
        private readonly offsetHighWaterMark: SessionOffsetHighWaterMark,
        public readonly teamId: number,
        public readonly sessionId: string,
        public readonly partition: number,
        public readonly topic: string,
        private readonly onFinish: (offsetsToRemove: number[]) => void
    ) {
        this.buffer = this.createBuffer()
    }

    private logContext = (): Record<string, any> => {
        const chunkStates: Record<string, any> = {}
        for (const [key, chunk] of this.chunks.entries()) {
            chunkStates[key] = chunk.logContext
        }

        return {
            sessionId: this.sessionId,
            partition: this.partition,
            teamId: this.teamId,
            topic: this.topic,
            oldestKafkaTimestamp: this.buffer.oldestKafkaTimestamp,
            oldestKafkaTimestampHumanReadable: this.buffer.oldestKafkaTimestamp
                ? DateTime.fromMillis(this.buffer.oldestKafkaTimestamp).toISO()
                : undefined,
            chunkStates,
            bufferCount: this.buffer.count,
        }
    }

    private async deleteFile(file: string, context: string) {
        try {
            await unlink(file)
        } catch (err) {
            if (err && err.code === 'ENOENT') {
                // could not delete file because it doesn't exist, so what?!
                return
            }
            status.error('🧨', `blob_ingester_session_manager failed deleting file ${context}path: ${file}`, {
                err,
                file,
                context,
            })
            captureException(err)
            throw err
        }
    }

    public async add(message: IncomingRecordingMessage): Promise<void> {
        if (this.destroying) {
            return
        }

        if (this.lastProcessedOffset === null) {
            this.lastProcessedOffset = (await this.offsetHighWaterMark.get(this.sessionId)) ?? -Infinity
        }

        if (message.metadata.offset <= this.lastProcessedOffset) {
            this.buffer.offsets.push(message.metadata.offset)
            return
        }

        if (message.chunk_count === 1) {
            await this.addToBuffer(message)
        } else {
            await this.addToChunks(message)
        }

        await this.flushIfBufferExceedsCapacity()
    }

    public get isEmpty(): boolean {
        return this.buffer.count === 0 && this.chunks.size === 0
    }

    public async flushIfBufferExceedsCapacity(): Promise<void> {
        if (this.destroying) {
            return
        }

        const bufferSizeKb = this.buffer.size / 1024
        const gzipSizeKb = bufferSizeKb * ESTIMATED_GZIP_COMPRESSION_RATIO
        const gzippedCapacity = gzipSizeKb / this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB

        if (gzippedCapacity > 1) {
            status.info('🚽', `blob_ingester_session_manager flushing buffer due to size`, {
                gzippedCapacity,
                gzipSizeKb,
                ...this.logContext(),
            })
            // return the promise and let the caller decide whether to await
            return this.flush('buffer_size')
        }
    }

    public async flushIfSessionBufferIsOld(referenceNow: number, flushThresholdMillis: number): Promise<void> {
        if (this.destroying) {
            return
        }

        const logContext: Record<string, any> = {
            ...this.logContext(),
            referenceTime: referenceNow,
            referenceTimeHumanReadable: DateTime.fromMillis(referenceNow).toISO(),
            flushThresholdMillis,
        }

        if (this.buffer.oldestKafkaTimestamp === null) {
            // We have no messages yet, so we can't flush
            if (this.buffer.count > 0) {
                throw new Error('Session buffer has messages but oldest timestamp is null. A paradox!')
            }
            status.warn('🚽', `blob_ingester_session_manager buffer has no oldestKafkaTimestamp yet`, { logContext })
            return
        }

        const bufferAge = referenceNow - this.buffer.oldestKafkaTimestamp
        logContext['bufferAge'] = bufferAge

        this.chunks = this.handleIdleChunks(this.chunks, referenceNow, flushThresholdMillis, logContext)

        if (bufferAge >= flushThresholdMillis) {
            status.info('🚽', `blob_ingester_session_manager flushing buffer due to age`, {
                ...logContext,
            })
            // return the promise and let the caller decide whether to await
            return this.flush('buffer_age')
        } else {
            status.info('🚽', `blob_ingester_session_manager not flushing buffer due to age`, {
                ...logContext,
            })
        }
    }

    handleIdleChunks(
        chunks: Map<string, PendingChunks>,
        referenceNow: number,
        flushThresholdMillis: number,
        logContext: Record<string, any>
    ): Map<string, PendingChunks> {
        const updatedChunks = new Map<string, PendingChunks>()

        for (const [key, pendingChunks] of chunks) {
            if (pendingChunks.isIdle(referenceNow, flushThresholdMillis)) {
                // dropping these chunks, don't lose their offsets
                pendingChunks.chunks.forEach((x) => {
                    // we want to make sure that the offsets for these messages we're ignoring
                    // are cleared from the offsetManager so, we add then to the buffer
                    // even though we're dropping the data
                    this.buffer.offsets.push(x.metadata.offset)
                })
                gaugePendingChunksDropped.inc()
                status.warn('🚽', `blob_ingester_session_manager dropping pending chunks due to age`, {
                    ...logContext,
                    chunkId: key,
                })
                continue
            }

            updatedChunks.set(key, pendingChunks)
        }

        return updatedChunks
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(reason: 'buffer_size' | 'buffer_age'): Promise<void> {
        if (this.flushBuffer) {
            return
        }

        if (this.destroying) {
            return
        }

        // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
        this.flushBuffer = this.buffer
        this.buffer = this.createBuffer()

        try {
            if (this.flushBuffer.count === 0) {
                throw new Error("Can't flush empty buffer")
            }

            const eventsRange = this.flushBuffer.eventsRange
            if (!eventsRange) {
                throw new Error("Can't flush buffer due to missing eventRange")
            }

            const { firstTimestamp, lastTimestamp } = eventsRange
            const baseKey = `${this.serverConfig.SESSION_RECORDING_REMOTE_FOLDER}/team_id/${this.teamId}/session_id/${this.sessionId}`
            const timeRange = `${firstTimestamp}-${lastTimestamp}`
            const dataKey = `${baseKey}/data/${timeRange}`

            const fileStream = createReadStream(this.flushBuffer.file).pipe(zlib.createGzip())

            this.inProgressUpload = new Upload({
                client: this.s3Client,
                params: {
                    Bucket: this.serverConfig.OBJECT_STORAGE_BUCKET,
                    Key: dataKey,
                    Body: fileStream,
                },
            })

            await this.inProgressUpload.done()

            await this.offsetHighWaterMark.set(
                this.sessionId,
                this.flushBuffer.offsets.sort((a, b) => a - b)[this.flushBuffer.offsets.length - 1]
            )

            fileStream.close()

            counterS3FilesWritten.labels(reason).inc(1)
            gaugeS3FilesBytesWritten.labels({ team: this.teamId }).set(this.flushBuffer.size)
            gaugeS3LinesWritten.set(this.flushBuffer.count)
        } catch (error) {
            if (error.name === 'AbortError' && this.destroying) {
                // abort of inProgressUpload while destroying is expected
                return
            }
            // TODO: If we fail to write to S3 we should be do something about it
            status.error('🧨', 'blob_ingester_session_manager failed writing session recording blob to S3', {
                error,
                ...this.logContext(),
                reason,
            })
            captureException(error)
            counterS3WriteErrored.inc()
        } finally {
            this.inProgressUpload = null
            await this.deleteFile(this.flushBuffer.file, 'on s3 flush')

            const offsets = this.flushBuffer.offsets
            this.flushBuffer = undefined

            // TODO: Sync the last processed offset to redis
            this.onFinish(offsets)
        }
    }

    private createBuffer(): SessionBuffer {
        try {
            const id = randomUUID()
            const buffer: SessionBuffer = {
                id,
                count: 0,
                size: 0,
                oldestKafkaTimestamp: null,
                file: path.join(
                    bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY),
                    `${this.teamId}.${this.sessionId}.${id}.jsonl`
                ),
                offsets: [],
                eventsRange: null,
            }

            // NOTE: We can't do this easily async as we would need to handle the race condition of multiple events coming in at once.
            writeFileSync(buffer.file, '', 'utf-8')

            return buffer
        } catch (error) {
            captureException(error, { tags: { team_id: this.teamId, session_id: this.sessionId } })
            throw error
        }
    }

    /**
     * Full messages (all chunks) are added to the buffer directly
     */
    private async addToBuffer(message: IncomingRecordingMessage): Promise<void> {
        try {
            this.buffer.oldestKafkaTimestamp = Math.min(
                this.buffer.oldestKafkaTimestamp ?? message.metadata.timestamp,
                message.metadata.timestamp
            )

            const messageData = convertToPersistedMessage(message)
            this.setEventsRangeFrom(message)

            const content = JSON.stringify(messageData) + '\n'
            this.buffer.count += 1
            this.buffer.size += Buffer.byteLength(content)
            this.buffer.offsets.push(message.metadata.offset)

            await appendFile(this.buffer.file, content, 'utf-8')
        } catch (error) {
            captureException(error, { extra: { message }, tags: { team_id: this.teamId, session_id: this.sessionId } })
            throw error
        }
    }

    /**
     * Chunked messages arrive over time or as duplicates
     * and are stored until there is a complete set
     * Once all chunks are received, the message is added to the buffer
     */
    private async addToChunks(message: IncomingRecordingMessage): Promise<void> {
        // If it is a chunked message we add to the collected chunks

        if (!this.chunks.has(message.chunk_id)) {
            this.chunks.set(message.chunk_id, new PendingChunks(message))
        } else {
            this.chunks.get(message.chunk_id)?.add(message)
        }
        const pendingChunks = this.chunks.get(message.chunk_id)

        if (!pendingChunks) {
            const { data, events_summary, ...messageToLog } = message
            captureMessage('No pending chunks when that is impossible', {
                extra: { ...messageToLog },
                tags: { team_id: this.teamId, session_id: this.sessionId, partition: this.partition },
            })
            throw new Error('It is impossible to have no pending chunks here')
        }

        if (pendingChunks.isComplete) {
            // If we have all the chunks, we can add the message to the buffer
            // We want to add all the chunk offsets as well so that they are tracked correctly
            await this.processChunksToBuffer(pendingChunks)
            this.chunks.delete(message.chunk_id)
        }
    }

    private async processChunksToBuffer(pendingChunks: PendingChunks): Promise<void> {
        pendingChunks.allChunkOffsets.forEach((offset) => this.buffer.offsets.push(offset))

        const completedChunks = pendingChunks.completedChunks

        await this.addToBuffer({
            ...completedChunks[0],
            data: completedChunks
                .sort((a, b) => a.chunk_index - b.chunk_index)
                .map((c) => c.data)
                .join(''),
        })
    }

    public async destroy(): Promise<void> {
        this.destroying = true
        if (this.inProgressUpload !== null) {
            await this.inProgressUpload.abort()
            this.inProgressUpload = null
        }

        const filePromises: Promise<void>[] = [this.flushBuffer?.file, this.buffer.file]
            .filter((x): x is string => x !== undefined)
            .map((x) =>
                this.deleteFile(x, 'on destroy').catch((error) => {
                    captureException(error, { tags: { team_id: this.teamId, session_id: this.sessionId } })
                    throw error
                })
            )
        await Promise.allSettled(filePromises)
    }

    private getEventRangeForMessage(message: IncomingRecordingMessage): [number | null, number | null] {
        try {
            if (!message.events_summary || !message.events_summary.length) {
                return [null, null]
            }

            return [
                message.events_summary[0].timestamp,
                message.events_summary[message.events_summary.length - 1].timestamp,
            ]
        } catch (e) {
            captureException(e, { tags: { team_id: this.teamId, session_id: this.sessionId }, extra: { message } })
            return [null, null]
        }
    }

    private setEventsRangeFrom(message: IncomingRecordingMessage) {
        const [start, end] = this.getEventRangeForMessage(message)

        if (start === null) {
            // if we don't have a start, then we can't have an end,
            // and we can't set new values for range
            captureMessage(
                "blob_ingester_session_manager: can't set events range from message without events summary",
                {
                    extra: { message },
                    tags: {
                        team_id: this.teamId,
                        session_id: this.sessionId,
                    },
                }
            )
            return
        }

        const firstTimestamp = Math.min(start, this.buffer.eventsRange?.firstTimestamp || Infinity)
        const lastTimestamp = Math.max(end || start, this.buffer.eventsRange?.lastTimestamp || -Infinity)

        this.buffer.eventsRange = { firstTimestamp, lastTimestamp }
    }
}
