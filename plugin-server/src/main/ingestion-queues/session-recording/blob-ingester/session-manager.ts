import { Upload } from '@aws-sdk/lib-storage'
import { captureException } from '@sentry/node'
import { randomUUID } from 'crypto'
import { createReadStream, writeFileSync } from 'fs'
import { appendFile, unlink } from 'fs/promises'
import path from 'path'
import { Counter, Gauge } from 'prom-client'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { ObjectStorage } from '../../../services/object_storage'
import { bufferFileDir } from '../session-recordings-blob-consumer'
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
    chunks: Map<string, IncomingRecordingMessage[]> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer
    destroying = false
    inProgressUpload: Upload | null = null

    constructor(
        public readonly serverConfig: PluginsServerConfig,
        public readonly s3Client: ObjectStorage['s3'],
        public readonly teamId: number,
        public readonly sessionId: string,
        public readonly partition: number,
        public readonly topic: string,
        private readonly onFinish: (offsetsToRemove: number[]) => void
    ) {
        this.buffer = this.createBuffer()

        // this.lastProcessedOffset = redis.get(`session-recording-last-offset-${this.sessionId}`) || 0
    }

    private async deleteFile(file: string, context: string) {
        try {
            await unlink(file)
            status.info('🗑️', `blob_ingester_session_manager deleted file ${context}`, { file, context })
        } catch (err) {
            if (err && err.code === 'ENOENT') {
                status.warn(
                    '🤷‍♀️',
                    `blob_ingester_session_manager failed deleting file ${context} path: ${file}, file not found. That's probably fine 🤷‍♀️`,
                    {
                        err,
                        file,
                        context,
                    }
                )
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
            status.warn('⚠️', `blob_ingester_session_manager add called after destroy`, {
                message,
                sessionId: this.sessionId,
                partition: this.partition,
            })
            return
        }

        this.buffer.oldestKafkaTimestamp = Math.min(
            this.buffer.oldestKafkaTimestamp ?? message.metadata.timestamp,
            message.metadata.timestamp
        )

        // TODO: Check that the offset is higher than the lastProcessed
        // If not - ignore it
        // If it is - update lastProcessed and process it
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
            status.warn('⚠️', `blob_ingester_session_manager flush on buffer size called after destroy`, {
                sessionId: this.sessionId,
                partition: this.partition,
            })
            return
        }

        const bufferSizeKb = this.buffer.size / 1024
        const gzipSizeKb = bufferSizeKb * ESTIMATED_GZIP_COMPRESSION_RATIO
        const gzippedCapacity = gzipSizeKb / this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB

        // even if the buffer is over-size we can't flush if we have unfinished chunks
        if (gzippedCapacity > 1) {
            if (this.chunks.size === 0) {
                // return the promise and let the caller decide whether to await
                status.info('🚽', `blob_ingester_session_manager flushing buffer due to size`, {
                    gzippedCapacity,
                    gzipSizeKb,
                    sessionId: this.sessionId,
                })
                return this.flush('buffer_size')
            } else {
                status.warn(
                    '🚽',
                    `blob_ingester_session_manager would flush buffer due to size, but chunks are still pending`,
                    {
                        gzippedCapacity,
                        sessionId: this.sessionId,
                        partition: this.partition,
                        chunks: this.chunks.size,
                    }
                )
            }
        }
    }

    public async flushIfSessionBufferIsOld(referenceNow: number, flushThresholdMillis: number): Promise<void> {
        if (this.destroying) {
            status.warn('⚠️', `blob_ingester_session_manager flush on age called after destroy`, {
                sessionId: this.sessionId,
                partition: this.partition,
            })
            return
        }

        if (this.buffer.oldestKafkaTimestamp === null) {
            // We have no messages yet, so we can't flush
            if (this.buffer.count > 0) {
                throw new Error('Session buffer has messages but oldest timestamp is null. A paradox!')
            }
            return
        }

        const bufferAge = referenceNow - this.buffer.oldestKafkaTimestamp

        if (bufferAge >= flushThresholdMillis) {
            const logContext = {
                bufferAge,
                sessionId: this.sessionId,
                partition: this.partition,
                chunkSize: this.chunks.size,
                oldestKafkaTimestamp: this.buffer.oldestKafkaTimestamp,
                referenceTime: referenceNow,
                flushThresholdMillis,
            }

            if (this.chunks.size > 0) {
                // there's a good chance that we're never going to get the rest of the chunks for this session,
                // and it will block offset commits
                // so, we're going to drop the chunks we have and hope for the best
                for (const [key, value] of this.chunks) {
                    value.forEach((x) => {
                        // we want to make sure that the offsets for these messages we're ignoring
                        // are cleared from the offsetManager so, we add then to the buffer we're about to flush
                        // even though we're dropping the data
                        this.buffer.offsets.push(x.metadata.offset)
                    })

                    captureException(
                        new Error(`Dropping chunks for while lagging and flushing due to age. This is maybe fine.`),
                        {
                            tags: {
                                sessionId: this.sessionId,
                            },
                            extra: {
                                chunkData: value,
                                key,
                                ...logContext,
                            },
                        }
                    )
                }
                this.chunks = new Map<string, IncomingRecordingMessage[]>()
            }

            if (this.chunks.size === 0) {
                // return the promise and let the caller decide whether to await
                status.info('🚽', `blob_ingester_session_manager flushing buffer due to age`, {
                    ...logContext,
                })
                return this.flush('buffer_age')
            } else {
                status.warn(
                    '🚽',
                    `blob_ingester_session_manager would flush buffer due to age, but chunks are still pending`,
                    {
                        ...logContext,
                    }
                )
            }
        }
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(reason: 'buffer_size' | 'buffer_age'): Promise<void> {
        if (this.flushBuffer) {
            status.warn('⚠️', "blob_ingester_session_manager Flush called but we're already flushing", {
                sessionId: this.sessionId,
                partition: this.partition,
                reason,
            })
            return
        }

        if (this.destroying) {
            status.warn('⚠️', `blob_ingester_session_manager flush somehow called after destroy`, {
                sessionId: this.sessionId,
                partition: this.partition,
                reason,
            })
            return
        }

        if (this.buffer.count === 0) {
            status.warn('⚠️', `blob_ingester_session_manager flush called but buffer is empty`, {
                sessionId: this.sessionId,
                partition: this.partition,
                reason,
            })
            return
        }

        // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
        this.flushBuffer = this.buffer
        this.buffer = this.createBuffer()

        const eventsRange = this.flushBuffer.eventsRange
        if (!eventsRange) {
            status.warn('⚠️', `blob_ingester_session_manager flush called but eventsRange is null`, {
                sessionId: this.sessionId,
                partition: this.partition,
                reason,
            })
            return
        }

        const { firstTimestamp, lastTimestamp } = eventsRange

        try {
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

            fileStream.close()

            counterS3FilesWritten.labels(reason).inc(1)
            gaugeS3FilesBytesWritten.labels({ team: this.teamId }).set(this.flushBuffer.size)
            gaugeS3LinesWritten.set(this.flushBuffer.count)
            status.info('🚽', `blob_ingester_session_manager - flushed buffer to S3`, {
                sessionId: this.sessionId,
                partition: this.partition,
                flushedSize: this.flushBuffer.size,
                flushedAge: this.flushBuffer.oldestKafkaTimestamp,
                flushedCount: this.flushBuffer.count,
                reason,
            })
        } catch (error) {
            if (error.name === 'AbortError' && this.destroying) {
                // abort of inProgressUpload while destroying is expected
                return
            }
            // TODO: If we fail to write to S3 we should be do something about it
            status.error('🧨', 'blob_ingester_session_manager failed writing session recording blob to S3', {
                error,
                sessionId: this.sessionId,
                partition: this.partition,
                team: this.teamId,
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
            status.error('🧨', 'blob_ingester_session_manager failed creating session recording buffer', {
                error,
                sessionId: this.sessionId,
                partition: this.partition,
            })
            captureException(error, { tags: { team_id: this.teamId, session_id: this.sessionId } })
            throw error
        }
    }

    /**
     * Full messages (all chunks) are added to the buffer directly
     */
    private async addToBuffer(message: IncomingRecordingMessage): Promise<void> {
        try {
            const messageData = convertToPersistedMessage(message)
            this.buffer.eventsRange = {
                firstTimestamp: Math.min(
                    message.events_summary[0].timestamp,
                    this.buffer.eventsRange?.firstTimestamp ?? Infinity
                ),
                lastTimestamp: Math.max(
                    message.events_summary[message.events_summary.length - 1].timestamp,
                    this.buffer.eventsRange?.lastTimestamp ?? 0
                ),
            }

            const content = JSON.stringify(messageData) + '\n'
            this.buffer.count += 1
            this.buffer.size += Buffer.byteLength(content)
            this.buffer.offsets.push(message.metadata.offset)

            await appendFile(this.buffer.file, content, 'utf-8')
        } catch (error) {
            status.error('🧨', 'blob_ingester_session_manager failed writing session recording buffer to disk', {
                error,
                sessionId: this.sessionId,
                partition: this.partition,
            })
            captureException(error, { extra: { message }, tags: { team_id: this.teamId, session_id: this.sessionId } })
            throw error
        }
    }

    /**
     * Chunked messages are added to the chunks map
     * Once all chunks are received, the message is added to the buffer
     *
     */
    private async addToChunks(message: IncomingRecordingMessage): Promise<void> {
        // If it is a chunked message we add to the collected chunks

        if (!this.chunks.has(message.chunk_id)) {
            this.chunks.set(message.chunk_id, [])
        }
        const chunks: IncomingRecordingMessage[] = this.chunks.get(message.chunk_id) || []
        chunks.push(message)

        if (chunks.length === message.chunk_count) {
            // If we have all the chunks, we can add the message to the buffer
            // We want to add all the chunk offsets as well so that they are tracked correctly
            chunks.forEach((x) => {
                this.buffer.offsets.push(x.metadata.offset)
            })

            await this.addToBuffer({
                ...message,
                data: chunks
                    .sort((a, b) => a.chunk_index - b.chunk_index)
                    .map((c) => c.data)
                    .join(''),
            })

            this.chunks.delete(message.chunk_id)
        }
    }

    public async destroy(): Promise<void> {
        this.destroying = true
        if (this.inProgressUpload !== null) {
            await this.inProgressUpload.abort()
            this.inProgressUpload = null
        }

        status.debug('␡', `blob_ingester_session_manager Destroying session manager`, { sessionId: this.sessionId })
        const filePromises: Promise<void>[] = [this.flushBuffer?.file, this.buffer.file]
            .filter((x): x is string => x !== undefined)
            .map((x) =>
                this.deleteFile(x, 'on destroy').catch((error) => {
                    status.error('🧨', 'blob_ingester_session_manager failed deleting session recording buffer', {
                        error,
                        sessionId: this.sessionId,
                        partition: this.partition,
                    })
                    captureException(error, { tags: { team_id: this.teamId, session_id: this.sessionId } })
                    throw error
                })
            )
        await Promise.allSettled(filePromises)
    }
}
