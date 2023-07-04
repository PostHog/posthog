import { Upload } from '@aws-sdk/lib-storage'
import { captureException, captureMessage } from '@sentry/node'
import { randomUUID } from 'crypto'
import { createReadStream, writeFileSync } from 'fs'
import { appendFile, readFile, unlink } from 'fs/promises'
import { DateTime } from 'luxon'
import path from 'path'
import { Counter, Gauge } from 'prom-client'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { ObjectStorage } from '../../../services/object_storage'
import { bufferFileDir } from '../session-recordings-blob-consumer'
import { RealtimeManager } from './realtime-manager'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage, now } from './utils'

export const counterRealtimeSnapshotSubscriptionStarted = new Counter({
    name: 'realtime_snapshots_subscription_started_counter',
    help: 'Indicates that this consumer received a request to subscribe to provide realtime snapshots for a session',
    labelNames: ['team_id'],
})

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

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    oldestKafkaTimestamp: number | null
    newestKafkaTimestamp: number | null
    count: number
    size: number
    file: string
    offsets: number[]
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
            status.info('🔌', 'blob_ingester_session_manager RealtimeManager subscribed to realtime snapshots', {
                teamId,
                sessionId,
            })
            counterRealtimeSnapshotSubscriptionStarted.inc({ team_id: teamId.toString() })
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

        await this.addToBuffer(message)
        await this.flushIfBufferExceedsCapacity()
    }

    public get isEmpty(): boolean {
        return this.buffer.count === 0
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

        const bufferAgeInMemory = now() - this.buffer.createdAt
        const bufferAgeFromReference = referenceNow - this.buffer.oldestKafkaTimestamp

        const bufferAgeIsOverThreshold = bufferAgeFromReference >= flushThresholdMillis
        // check the in-memory age against a larger value than the flush threshold,
        // otherwise we'll flap between reasons for flushing when close to real-time processing
        const sessionAgeIsOverThreshold = bufferAgeInMemory >= flushThresholdMillis * 2

        logContext['bufferAgeInMemory'] = bufferAgeInMemory
        logContext['bufferAgeFromReference'] = bufferAgeFromReference
        logContext['bufferAgeIsOverThreshold'] = bufferAgeIsOverThreshold
        logContext['sessionAgeIsOverThreshold'] = sessionAgeIsOverThreshold

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
                errorMessage: `${error.name || 'Unknown Error Type'}: ${error.message}`,
                error,
                ...this.logContext(),
                reason,
            })
            captureException(error)
            counterS3WriteErrored.inc()
        } finally {
            this.inProgressUpload = null
            // We turn off real time as the file will now be in S3
            this.realtime = false
            const { file, offsets } = this.flushBuffer
            // We want to delete the flush buffer before we proceed so that the onFinish handler doesn't reference it
            this.flushBuffer = undefined
            this.onFinish(offsets)
            await this.deleteFile(file, 'on s3 flush')
        }
    }

    private createBuffer(): SessionBuffer {
        try {
            const id = randomUUID()
            const buffer: SessionBuffer = {
                id,
                createdAt: now(),
                count: 0,
                size: 0,
                oldestKafkaTimestamp: null,
                newestKafkaTimestamp: null,
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

            this.buffer.newestKafkaTimestamp = Math.max(
                this.buffer.newestKafkaTimestamp ?? message.metadata.timestamp,
                message.metadata.timestamp
            )

            const messageData = convertToPersistedMessage(message)
            this.setEventsRangeFrom(message)

            const content = JSON.stringify(messageData) + '\n'
            this.buffer.count += 1
            this.buffer.size += Buffer.byteLength(content)
            this.buffer.offsets.push(message.metadata.offset)
            // It is important that we sort the offsets as the parent expects these to be sorted
            this.buffer.offsets.sort((a, b) => a - b)

            if (this.realtime) {
                // We don't care about the response here as it is an optimistic call
                void this.realtimeManager.addMessage(message)
            }

            await appendFile(this.buffer.file, content, 'utf-8')
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

    public getLowestOffset(): number | null {
        if (this.buffer.offsets.length === 0) {
            return null
        }
        return Math.min(this.buffer.offsets[0], this.flushBuffer?.offsets[0] ?? Infinity)
    }
}
