import { Upload } from '@aws-sdk/lib-storage'
import { captureException, captureMessage } from '@sentry/node'
import { randomUUID } from 'crypto'
import { createReadStream, createWriteStream } from 'fs'
import { stat, unlink } from 'fs/promises'
import { DateTime } from 'luxon'
import path from 'path'
import { Counter, Histogram } from 'prom-client'
import { PassThrough, Transform } from 'stream'
import { pipeline } from 'stream/promises'
import { Tail } from 'tail'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { timeoutGuard } from '../../../../utils/db/utils'
import { status } from '../../../../utils/status'
import { asyncTimeoutGuard } from '../../../../utils/timing'
import { ObjectStorage } from '../../../services/object_storage'
import { IncomingRecordingMessage } from '../types'
import { bufferFileDir, convertForPersistence, getLagMultiplier, maxDefined, minDefined, now } from '../utils'
import { OffsetHighWaterMarker } from './offset-high-water-marker'
import { RealtimeManager } from './realtime-manager'

const BUCKETS_LINES_WRITTEN = [0, 10, 50, 100, 500, 1000, 2000, 5000, 10000, Infinity]
export const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]
const S3_UPLOAD_WARN_TIME_SECONDS = 2 * 60 * 1000

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
    buckets: BUCKETS_LINES_WRITTEN,
})

const histogramS3KbWritten = new Histogram({
    name: 'recording_blob_ingestion_s3_kb_written',
    help: 'The uncompressed size of file we send to S3',
    buckets: BUCKETS_KB_WRITTEN,
})

const histogramSessionAgeSeconds = new Histogram({
    name: 'recording_blob_ingestion_session_age_seconds',
    help: 'The age of current sessions in seconds',
    buckets: [0, 60, 60 * 2, 60 * 5, 60 * 8, 60 * 10, 60 * 12, 60 * 15, 60 * 20, Infinity],
})

const histogramSessionSizeKb = new Histogram({
    name: 'recording_blob_ingestion_session_size_kb',
    help: 'The size of current sessions in kb',
    buckets: BUCKETS_KB_WRITTEN,
})

const histogramFlushTimeSeconds = new Histogram({
    name: 'recording_blob_ingestion_session_flush_time_seconds',
    help: 'The time taken to flush a session in seconds',
    buckets: [0, 2, 5, 10, 20, 30, 60, 120, 180, 300, Infinity],
})

const histogramSessionSize = new Histogram({
    name: 'recording_blob_ingestion_session_lines',
    help: 'The size of sessions in numbers of lines',
    buckets: BUCKETS_LINES_WRITTEN,
})

const writeStreamBlocked = new Counter({
    name: 'recording_blob_ingestion_write_stream_blocked',
    help: 'Number of times we get blocked by the stream backpressure',
})

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    oldestKafkaTimestamp: number | null
    newestKafkaTimestamp: number | null
    sizeEstimate: number
    count: number
    file: (type: 'jsonl' | 'gz') => string
    fileStream: Transform
    offsets: {
        lowest?: number
        highest?: number
    }
    eventsRange: {
        firstTimestamp: number
        lastTimestamp: number
    } | null
    createdAt: number
}

const MAX_FLUSH_TIME_MS = 60 * 1000

export class SessionManager {
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer
    flushPromise?: Promise<void>
    destroying = false
    inProgressUpload: Upload | null = null
    unsubscribe: () => void
    flushJitterMultiplier: number
    realtimeTail: Tail | null = null

    constructor(
        public readonly serverConfig: PluginsServerConfig,
        public readonly s3Client: ObjectStorage['s3'],
        public readonly realtimeManager: RealtimeManager,
        public readonly offsetHighWaterMarker: OffsetHighWaterMarker,
        public readonly teamId: number,
        public readonly sessionId: string,
        public readonly partition: number,
        public readonly topic: string,
        public readonly debug: boolean = false
    ) {
        this.buffer = this.createBuffer()

        // NOTE: a new SessionManager indicates that either everything has been flushed or a rebalance occured so we should clear the existing redis messages
        void realtimeManager.clearAllMessages(this.teamId, this.sessionId)

        this.unsubscribe = realtimeManager.onSubscriptionEvent(this.teamId, this.sessionId, () => {
            void this.startRealtime()
        })

        // We add a jitter multiplier to the buffer age so that we don't have all sessions flush at the same time
        this.flushJitterMultiplier = 1 - Math.random() * serverConfig.SESSION_RECORDING_BUFFER_AGE_JITTER

        this.debugLog('📦', '[session-manager] started new manager', {
            partition,
            topic,
            sessionId,
            teamId,
        })
    }

    /**
     * when debug logging we don't want to see every session's logs,
     * or it becomes impossible to see the wood for the trees
     * so we only log if we are debugging this session
     */
    private debugLog(icon: string, message: string, extra: object): void {
        if (!this.debug) {
            return
        }
        status.debug(icon, message, extra)
    }

    private captureException(error: Error, extra: Record<string, any> = {}): void {
        const context = this.logContext()
        captureException(error, {
            extra: { ...context, ...extra },
            tags: { teamId: context.teamId, sessionId: context.sessionId, partition: context.partition },
        })
    }

    private captureMessage(message: string, extra: Record<string, any> = {}): void {
        const context = this.logContext()
        captureMessage(message, {
            extra: { ...context, ...extra },
            tags: { teamId: context.teamId, sessionId: context.sessionId, partition: context.partition },
        })
    }

    public async add(message: IncomingRecordingMessage): Promise<void> {
        if (this.destroying) {
            this.debugLog('🚽', '[session-manager] add called but we are in a destroying state', {
                ...this.logContext(),
            })
            return
        }

        try {
            this.buffer.oldestKafkaTimestamp = Math.min(
                this.buffer.oldestKafkaTimestamp ?? message.metadata.timestamp,
                message.metadata.timestamp
            )

            this.buffer.newestKafkaTimestamp = Math.max(
                this.buffer.newestKafkaTimestamp ?? message.metadata.timestamp,
                message.metadata.timestamp
            )

            const content =
                convertForPersistence(message.eventsByWindowId)
                    .map((x) => JSON.stringify(x))
                    .join('\n') + '\n'

            this.buffer.count += 1
            this.buffer.sizeEstimate += content.length
            this.buffer.offsets.lowest = minDefined(this.buffer.offsets.lowest, message.metadata.lowOffset)
            this.buffer.offsets.highest = maxDefined(this.buffer.offsets.highest, message.metadata.highOffset)
            this.buffer.eventsRange = {
                firstTimestamp:
                    minDefined(message.eventsRange.start, this.buffer.eventsRange?.firstTimestamp) ??
                    message.eventsRange.start,
                lastTimestamp:
                    maxDefined(message.eventsRange.end, this.buffer.eventsRange?.lastTimestamp) ??
                    message.eventsRange.end,
            }

            if (!this.buffer.fileStream.write(content, 'utf-8')) {
                writeStreamBlocked.inc()
                await new Promise((r) => this.buffer.fileStream.once('drain', r))
            }
        } catch (error) {
            this.captureException(error, { message })
            throw error
        }

        // NOTE: This is uncompressed size estimate but that's okay as we currently want to over-flush to see if we can shake out a bug
        const shouldAttemptFlush =
            this.buffer.sizeEstimate >= this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB * 1024
        if (shouldAttemptFlush) {
            await this.flush('buffer_size')
        }

        this.debugLog('🚽', `[session-manager] added message`, {
            ...this.logContext(),
            metadata: message.metadata,
            shouldAttemptFlush,
        })
    }

    public get isEmpty(): boolean {
        return !this.buffer.count && !this.flushBuffer?.count
    }

    public async flushIfSessionBufferIsOld(referenceNow: number, partitionLag = 0): Promise<void> {
        if (this.destroying) {
            return
        }

        const lagMultiplier = getLagMultiplier(partitionLag)

        const flushThresholdMs = this.serverConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000
        const flushThresholdJitteredMs = flushThresholdMs * this.flushJitterMultiplier
        const flushThresholdMemoryMs =
            flushThresholdJitteredMs *
            (lagMultiplier < 1 ? lagMultiplier : this.serverConfig.SESSION_RECORDING_BUFFER_AGE_IN_MEMORY_MULTIPLIER)

        const logContext: Record<string, any> = {
            ...this.logContext(),
            referenceTime: referenceNow,
            referenceTimeHumanReadable: DateTime.fromMillis(referenceNow).toISO(),
            flushThresholdMs,
            flushThresholdJitteredMs,
            flushThresholdMemoryMs,
        }

        this.debugLog('🚽', `[session-manager]  - [PARTITION DEBUG] - flushIfSessionBufferIsOld?`, { logContext })

        if (this.buffer.oldestKafkaTimestamp === null) {
            // We have no messages yet, so we can't flush
            if (this.buffer.count > 0) {
                throw new Error('Session buffer has messages but oldest timestamp is null. A paradox!')
            }
            this.debugLog('🚽', `[session-manager] buffer has no oldestKafkaTimestamp yet`, { logContext })
            return
        }

        const bufferAgeInMemoryMs = now() - this.buffer.createdAt
        const bufferAgeFromReferenceMs = referenceNow - this.buffer.oldestKafkaTimestamp

        // check the in-memory age against a larger value than the flush threshold,
        // otherwise we'll flap between reasons for flushing when close to real-time processing
        const isSessionAgeOverThreshold = bufferAgeInMemoryMs >= flushThresholdMemoryMs
        const isBufferAgeOverThreshold = bufferAgeFromReferenceMs >= flushThresholdJitteredMs

        logContext['bufferAgeInMemoryMs'] = bufferAgeInMemoryMs
        logContext['bufferAgeFromReferenceMs'] = bufferAgeFromReferenceMs
        logContext['isBufferAgeOverThreshold'] = isBufferAgeOverThreshold
        logContext['isSessionAgeOverThreshold'] = isSessionAgeOverThreshold

        histogramSessionAgeSeconds.observe(bufferAgeInMemoryMs / 1000)
        histogramSessionSize.observe(this.buffer.count)
        histogramSessionSizeKb.observe(this.buffer.sizeEstimate / 1024)

        if (isBufferAgeOverThreshold || isSessionAgeOverThreshold) {
            return this.flush(isBufferAgeOverThreshold ? 'buffer_age' : 'buffer_age_realtime')
        }
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */

    public async flush(
        reason: 'buffer_size' | 'buffer_age' | 'buffer_age_realtime' | 'partition_shutdown'
    ): Promise<void> {
        if (!this.flushPromise) {
            this.flushPromise = this._flush(reason).finally(() => {
                this.flushPromise = undefined
            })
        }

        return this.flushPromise
    }
    private async _flush(
        reason: 'buffer_size' | 'buffer_age' | 'buffer_age_realtime' | 'partition_shutdown'
    ): Promise<void> {
        // NOTE: The below checks don't need to throw really but we do so to help debug what might be blocking things
        if (this.flushBuffer) {
            this.debugLog('🚽', '[session-manager] flush called but we already have a flush buffer', {
                ...this.logContext(),
            })
            return
        }

        if (this.destroying) {
            this.debugLog('🚽', '[session-manager] flush called but we are in a destroying state', {
                ...this.logContext(),
            })
            return
        }

        const flushTimeout = setTimeout(() => {
            status.error('🧨', '[session-manager] flush timed out', {
                ...this.logContext(),
            })

            this.captureMessage('[session-manager] flush timed out')
            this.endFlush()
        }, MAX_FLUSH_TIME_MS)

        const endFlushTimer = histogramFlushTimeSeconds.startTimer()

        try {
            // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
            this.flushBuffer = this.buffer
            this.buffer = this.createBuffer()
            this.stopRealtime()
            // We don't want to keep writing unecessarily...
            const { fileStream, file, count, eventsRange, sizeEstimate } = this.flushBuffer

            if (count === 0) {
                throw new Error("Can't flush empty buffer")
            }

            if (!eventsRange) {
                throw new Error("Can't flush buffer due to missing eventRange")
            }

            const { firstTimestamp, lastTimestamp } = eventsRange
            const baseKey = `${this.serverConfig.SESSION_RECORDING_REMOTE_FOLDER}/team_id/${this.teamId}/session_id/${this.sessionId}`
            const timeRange = `${firstTimestamp}-${lastTimestamp}`
            const dataKey = `${baseKey}/data/${timeRange}`

            // We want to ensure the writeStream has ended before we read from it
            await asyncTimeoutGuard({ message: 'session-manager.flush ending write stream delayed.' }, async () => {
                await new Promise((r) => fileStream.end(r))
            })

            const readStream = createReadStream(file('gz'))

            readStream.on('error', (err) => {
                // TODO: What should we do here?
                status.error('🧨', '[session-manager] readstream errored', {
                    ...this.logContext(),
                    error: err,
                })

                this.captureException(err)
            })

            const inProgressUpload = (this.inProgressUpload = new Upload({
                client: this.s3Client,
                params: {
                    Bucket: this.serverConfig.OBJECT_STORAGE_BUCKET,
                    Key: dataKey,
                    ContentEncoding: 'gzip',
                    ContentType: 'application/json',
                    Body: readStream,
                },
            }))

            await asyncTimeoutGuard(
                {
                    message: 'session-manager.flush uploading file to S3 delayed.',
                    timeout: S3_UPLOAD_WARN_TIME_SECONDS,
                },
                async () => {
                    await inProgressUpload.done()
                }
            )

            readStream.close()

            counterS3FilesWritten.labels(reason).inc(1)
            histogramS3LinesWritten.observe(count)
            histogramS3KbWritten.observe(sizeEstimate / 1024)
            this.endFlush()
        } catch (error: any) {
            // TRICKY: error can for some reason sometimes be undefined...
            error = error || new Error('Unknown Error')

            if (error.name === 'AbortError' && this.destroying) {
                // abort of inProgressUpload while destroying is expected
                return
            }

            await this.inProgressUpload?.abort()

            // TODO: If we fail to write to S3 we should be do something about it
            status.error('🧨', '[session-manager] failed writing session recording blob to S3', {
                errorMessage: `${error.name || 'Unknown Error Type'}: ${error.message}`,
                error,
                ...this.logContext(),
                reason,
            })
            this.captureException(error)
            counterS3WriteErrored.inc()

            throw error
        } finally {
            clearTimeout(flushTimeout)
            endFlushTimer()
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
            // We want to delete the flush buffer before we proceed so that the onFinish handler doesn't reference it
            void this.destroyBuffer(this.flushBuffer)
            this.flushBuffer = undefined
            if (offsets.highest) {
                void this.offsetHighWaterMarker.add(
                    { topic: this.topic, partition: this.partition },
                    this.sessionId,
                    offsets.highest
                )
            }
        } catch (error) {
            this.captureException(error)
        } finally {
            clearTimeout(timeout)
        }
    }

    private createBuffer(): SessionBuffer {
        try {
            const id = randomUUID()
            const fileBase = path.join(
                bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY),
                `${this.teamId}.${this.sessionId}.${id}`
            )

            const file = (type: 'jsonl' | 'gz') => `${fileBase}.${type}`

            const writeStream = new PassThrough()

            // The compressed file
            pipeline(writeStream, zlib.createGzip(), createWriteStream(file('gz'))).catch((error) => {
                // TODO: If this actually happens we probably want to destroy the buffer as we will be stuck...
                status.error('🧨', '[session-manager] writestream errored', {
                    ...this.logContext(),
                    error,
                })

                this.captureException(error)
            })

            // The uncompressed file which we need for realtime playback
            pipeline(writeStream, createWriteStream(file('jsonl'))).catch((error) => {
                // TODO: If this actually happens we probably want to destroy the buffer as we will be stuck...
                status.error('🧨', '[session-manager] writestream errored', {
                    ...this.logContext(),
                    error,
                })

                this.captureException(error)
            })

            const buffer: SessionBuffer = {
                id,
                createdAt: now(),
                count: 0,
                sizeEstimate: 0,
                oldestKafkaTimestamp: null,
                newestKafkaTimestamp: null,
                file,
                fileStream: writeStream,
                offsets: {},
                eventsRange: null,
            }

            return buffer
        } catch (error) {
            this.captureException(error)
            throw error
        }
    }

    private startRealtime() {
        if (this.realtimeTail) {
            return
        }

        this.debugLog('⚡️', `[session-manager][realtime] Started `, { sessionId: this.sessionId })

        this.realtimeTail = new Tail(this.buffer.file('jsonl'), {
            fromBeginning: true,
        })

        this.realtimeTail.on('line', async (data: string) => {
            await this.realtimeManager.addMessagesFromBuffer(this.teamId, this.sessionId, data, Date.now())
        })

        this.realtimeTail.on('error', (error) => {
            status.error('🧨', '[session-manager][realtime] failed to watch buffer file', {
                sessionId: this.sessionId,
                teamId: this.teamId,
            })
            this.captureException(error)
            this.stopRealtime()
        })
    }

    private stopRealtime() {
        if (this.realtimeTail) {
            this.realtimeTail.unwatch()
            this.realtimeTail = null
        }
    }

    public async destroy(): Promise<void> {
        this.destroying = true
        this.unsubscribe()
        this.stopRealtime()
        if (this.inProgressUpload !== null) {
            await this.inProgressUpload.abort().catch((error) => {
                status.error('🧨', '[session-manager][realtime] failed to abort in progress upload', {
                    ...this.logContext(),
                    error,
                })
                this.captureException(error)
            })
            this.inProgressUpload = null
        }

        if (this.flushBuffer) {
            await this.destroyBuffer(this.flushBuffer)
        }
        await this.destroyBuffer(this.buffer)
    }

    public getLowestOffset(): number | null {
        return minDefined(this.buffer.offsets.lowest, this.flushBuffer?.offsets.lowest) ?? null
    }

    private async destroyBuffer(buffer: SessionBuffer): Promise<void> {
        await new Promise<void>((resolve) => {
            buffer.fileStream.end(async () => {
                await Promise.allSettled(
                    [buffer.file('gz'), buffer.file('jsonl')].map(async (file) => {
                        await stat(file)
                        await unlink(file)
                    })
                )
                resolve()
            })
        })
    }

    private logContext = () => {
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
            ...(this.debug ? this.toJSON() : {}),
        }
    }

    public toJSON(): Record<string, any> {
        return {
            isEmpty: this.isEmpty,
            lowestOffset: this.getLowestOffset(),
            buffer: {
                id: this.buffer.id,
                oldestKafkaTimestamp: this.buffer.oldestKafkaTimestamp,
                newestKafkaTimestamp: this.buffer.newestKafkaTimestamp,
                sizeEstimate: this.buffer.sizeEstimate,
                count: this.buffer.count,
                file: this.buffer.file('jsonl'),
                offsets: this.buffer.offsets,
                eventsRange: this.buffer.eventsRange,
                createdAt: this.buffer.createdAt,
            },
            flushBuffer: this.flushBuffer
                ? {
                      id: this.flushBuffer.id,
                      oldestKafkaTimestamp: this.flushBuffer.oldestKafkaTimestamp,
                      newestKafkaTimestamp: this.flushBuffer.newestKafkaTimestamp,
                      sizeEstimate: this.flushBuffer.sizeEstimate,
                      count: this.flushBuffer.count,
                      file: this.flushBuffer.file('jsonl'),
                      offsets: this.flushBuffer.offsets,
                      eventsRange: this.flushBuffer.eventsRange,
                      createdAt: this.flushBuffer.createdAt,
                  }
                : null,
            partition: this.partition,
            destroying: this.destroying,
        }
    }
}
