import { Upload } from '@aws-sdk/lib-storage'
import { captureException, captureMessage } from '@sentry/node'
import { randomUUID } from 'crypto'
import { createReadStream, createWriteStream, WriteStream } from 'fs'
import { readFile, stat, unlink } from 'fs/promises'
import { DateTime } from 'luxon'
import path from 'path'
import { Counter, Histogram } from 'prom-client'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'
import { ObjectStorage } from '../../../services/object_storage'
import { bufferFileDir } from '../session-recordings-blob-consumer'
import { RealtimeManager } from './realtime-manager'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage, now } from './utils'

const counterS3FilesWritten = new Counter({
    name: 'recording_s3_files_written',
    help: 'A single file flushed to S3',
    labelNames: ['flushReason'],
})

const counterS3WriteErrored = new Counter({
    name: 'recording_s3_write_errored',
    help: 'Indicates that we failed to flush to S3 without recovering',
})

const histogramS3LinesWritten = new Histogram({
    name: 'recording_s3_lines_written_histogram',
    help: 'The number of lines in a file we send to s3',
    buckets: [0, 50, 100, 150, 200, 300, 400, 500, 750, 1000, 2000, 5000, Infinity],
})

const histogramSessionAgeSeconds = new Histogram({
    name: 'recording_blob_ingestion_session_age_seconds',
    help: 'The age of current sessions in seconds',
    buckets: [0, 60, 60 * 2, 60 * 5, 60 * 8, 60 * 10, 60 * 12, 60 * 15, 60 * 20, Infinity],
})

const histogramSessionSize = new Histogram({
    name: 'recording_blob_ingestion_session_lines',
    help: 'The size of sessions in numbers of lines',
    buckets: [0, 50, 100, 150, 200, 300, 400, 500, 750, 1000, 2000, 5000, Infinity],
})

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    oldestKafkaTimestamp: number | null
    newestKafkaTimestamp: number | null
    count: number
    file: string
    fileStream: WriteStream
    offsets: {
        lowest: number
        highest: number
    }
    eventsRange: {
        firstTimestamp: number
        lastTimestamp: number
    } | null
    createdAt: number
}

export class SessionManager {
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer
    destroying = false
    realtime = false
    inProgressUpload: Upload | null = null
    unsubscribe: () => void

    constructor(
        public readonly serverConfig: PluginsServerConfig,
        public readonly s3Client: ObjectStorage['s3'],
        public readonly realtimeManager: RealtimeManager,
        public readonly teamId: number,
        public readonly sessionId: string,
        public readonly partition: number,
        public readonly topic: string,
        private readonly onFinish: (offsetsToRemove: number[]) => void
    ) {
        this.buffer = this.createBuffer()

        // NOTE: a new SessionManager indicates that either everything has been flushed or a rebalance occured so we should clear the existing redis messages
        void realtimeManager.clearAllMessages(this.teamId, this.sessionId)

        this.unsubscribe = realtimeManager.onSubscriptionEvent(this.teamId, this.sessionId, () => {
            void this.startRealtime()
        })
    }

    private logContext = (): Record<string, any> => {
        return {
            sessionId: this.sessionId,
            partition: this.partition,
            teamId: this.teamId,
            topic: this.topic,
            oldestKafkaTimestamp: this.buffer.oldestKafkaTimestamp,
            oldestKafkaTimestampHumanReadable: this.buffer.oldestKafkaTimestamp
                ? DateTime.fromMillis(this.buffer.oldestKafkaTimestamp).toISO()
                : undefined,
            bufferCount: this.buffer.count,
        }
    }

    public add(message: IncomingRecordingMessage): void {
        if (this.destroying) {
            return
        }

        this.addToBuffer(message)
    }

    public get isEmpty(): boolean {
        return !this.buffer.count && !this.flushBuffer?.count
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

        const bufferAgeInMemory = now() - this.buffer.createdAt
        const bufferAgeFromReference = referenceNow - this.buffer.oldestKafkaTimestamp

        const bufferAgeIsOverThreshold = bufferAgeFromReference >= flushThresholdMillis
        // check the in-memory age against a larger value than the flush threshold,
        // otherwise we'll flap between reasons for flushing when close to real-time processing
        const sessionAgeIsOverThreshold =
            bufferAgeInMemory >=
            flushThresholdMillis * this.serverConfig.SESSION_RECORDING_BUFFER_AGE_IN_MEMORY_MULTIPLIER

        logContext['bufferAgeInMemory'] = bufferAgeInMemory
        logContext['bufferAgeFromReference'] = bufferAgeFromReference
        logContext['bufferAgeIsOverThreshold'] = bufferAgeIsOverThreshold
        logContext['sessionAgeIsOverThreshold'] = sessionAgeIsOverThreshold

        histogramSessionAgeSeconds.observe(bufferAgeInMemory / 1000)
        histogramSessionSize.observe(this.buffer.count)

        if (bufferAgeIsOverThreshold || sessionAgeIsOverThreshold) {
            status.info('🚽', `blob_ingester_session_manager flushing buffer due to age`, {
                ...logContext,
            })

            // return the promise and let the caller decide whether to await
            return this.flush(bufferAgeIsOverThreshold ? 'buffer_age' : 'buffer_age_realtime')
        } else {
            status.info('🚽', `blob_ingester_session_manager not flushing buffer due to age`, {
                ...logContext,
            })
        }
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(reason: 'buffer_size' | 'buffer_age' | 'buffer_age_realtime'): Promise<void> {
        if (this.flushBuffer) {
            return
        }

        if (this.destroying) {
            return
        }

        // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
        this.flushBuffer = this.buffer
        this.buffer = this.createBuffer()
        const { fileStream, file } = this.flushBuffer
        const timeout = timeoutGuard(`session-manager.flush delayed. Waiting over 30 seconds.`)

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

            await new Promise<void>((resolve, reject) => {
                // We need to safely end the file before reading from it
                fileStream.end(async () => {
                    try {
                        const fileStream = createReadStream(file).pipe(zlib.createGzip())

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
                        resolve()
                    } catch (error) {
                        reject(error)
                    }
                })
            })

            counterS3FilesWritten.labels(reason).inc(1)
            histogramS3LinesWritten.observe(this.flushBuffer.count)
        } catch (error) {
            if (error.name === 'AbortError' && this.destroying) {
                // abort of inProgressUpload while destroying is expected
                return
            }
            // TODO: If we fail to write to S3 we should be do something about it
            status.error('🧨', 'blob_ingester_session_manager failed writing session recording blob to S3', {
                errorMessage: `${error.name || 'Unknown Error Type'}: ${error.message}`,
                error,
                ...this.logContext(),
                reason,
            })
            captureException(error)
            counterS3WriteErrored.inc()
        } finally {
            clearTimeout(timeout)
            this.endFlush()
        }
    }

    private endFlush(): void {
        if (!this.flushBuffer) {
            return
        }
        const { offsets } = this.flushBuffer
        const timeout = timeoutGuard(`session-manager.endFlush delayed. Waiting over 30 seconds.`)
        try {
            this.inProgressUpload = null
            // We turn off real time as the file will now be in S3
            this.realtime = false
            // We want to delete the flush buffer before we proceed so that the onFinish handler doesn't reference it
            void this.destroyBuffer(this.flushBuffer)
            this.flushBuffer = undefined
            this.onFinish([offsets.lowest, offsets.highest])
        } catch (error) {
            captureException(error)
        } finally {
            clearTimeout(timeout)
        }
    }

    private createBuffer(): SessionBuffer {
        try {
            const id = randomUUID()
            const file = path.join(
                bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY),
                `${this.teamId}.${this.sessionId}.${id}.jsonl`
            )
            const buffer: SessionBuffer = {
                id,
                createdAt: now(),
                count: 0,
                oldestKafkaTimestamp: null,
                newestKafkaTimestamp: null,
                file,
                fileStream: createWriteStream(file, 'utf-8'),
                offsets: {
                    lowest: Infinity,
                    highest: -Infinity,
                },
                eventsRange: null,
            }

            return buffer
        } catch (error) {
            captureException(error, { tags: { team_id: this.teamId, session_id: this.sessionId } })
            throw error
        }
    }

    /**
     * Full messages (all chunks) are added to the buffer directly
     */
    private addToBuffer(message: IncomingRecordingMessage): void {
        try {
            this.buffer.oldestKafkaTimestamp = Math.min(
                this.buffer.oldestKafkaTimestamp ?? message.metadata.timestamp,
                message.metadata.timestamp
            )

            this.buffer.newestKafkaTimestamp = Math.max(
                this.buffer.newestKafkaTimestamp ?? message.metadata.timestamp,
                message.metadata.timestamp
            )

            const messageData = convertToPersistedMessage(message)
            this.setEventsRangeFrom(message)

            const content = JSON.stringify(messageData) + '\n'
            this.buffer.count += 1
            this.buffer.offsets.lowest = Math.min(this.buffer.offsets.lowest, message.metadata.offset)
            this.buffer.offsets.highest = Math.max(this.buffer.offsets.highest, message.metadata.offset)

            if (this.realtime) {
                // We don't care about the response here as it is an optimistic call
                void this.realtimeManager.addMessage(message)
            }

            this.buffer.fileStream.write(content)
        } catch (error) {
            captureException(error, { extra: { message }, tags: { team_id: this.teamId, session_id: this.sessionId } })
            throw error
        }
    }
    private setEventsRangeFrom(message: IncomingRecordingMessage) {
        const start = message.events.at(0)?.timestamp
        const end = message.events.at(-1)?.timestamp

        if (!start || !end) {
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

    private async startRealtime() {
        if (this.realtime) {
            return
        }

        status.info('⚡️', `blob_ingester_session_manager Real-time mode started `, { sessionId: this.sessionId })

        this.realtime = true

        try {
            const timestamp = this.buffer.oldestKafkaTimestamp ?? 0
            const existingContent = await readFile(this.buffer.file, 'utf-8')
            await this.realtimeManager.addMessagesFromBuffer(this.teamId, this.sessionId, existingContent, timestamp)
            status.info('⚡️', 'blob_ingester_session_manager loaded existing snapshot buffer into realtime', {
                sessionId: this.sessionId,
                teamId: this.teamId,
            })
        } catch (e) {
            status.error('🧨', 'blob_ingester_session_manager failed loading existing snapshot buffer', {
                sessionId: this.sessionId,
                teamId: this.teamId,
            })
            captureException(e)
        }
    }

    public async destroy(): Promise<void> {
        this.destroying = true
        this.unsubscribe()
        if (this.inProgressUpload !== null) {
            await this.inProgressUpload.abort().catch((error) => {
                status.error('🧨', 'blob_ingester_session_manager failed to abort in progress upload', {
                    ...this.logContext(),
                    error,
                })
                captureException(error, { tags: this.logContext() })
            })
            this.inProgressUpload = null
        }

        if (this.flushBuffer) {
            await this.destroyBuffer(this.flushBuffer)
        }
        await this.destroyBuffer(this.buffer)
    }

    public getLowestOffset(): number | null {
        if (this.buffer.count === 0) {
            return null
        }
        return Math.min(this.buffer.offsets.lowest, this.flushBuffer?.offsets.lowest ?? Infinity)
    }

    private async destroyBuffer(buffer: SessionBuffer): Promise<void> {
        await new Promise<void>((resolve) => {
            buffer.fileStream.close(async () => {
                try {
                    await stat(buffer.file)
                    await unlink(buffer.file)
                } catch (error) {
                    // Indicates the file was already deleted (i.e. if there was never any data in the buffer)
                }

                resolve()
            })
        })
    }
}
