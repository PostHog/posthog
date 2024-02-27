import { Upload } from '@aws-sdk/lib-storage'
import { captureException, captureMessage } from '@sentry/node'
import { createReadStream, createWriteStream, WriteStream } from 'fs'
import { mkdir, readdir, readFile, rename, rmdir, stat, unlink, writeFile } from 'fs/promises'
import path from 'path'
import { Counter, Histogram } from 'prom-client'
import { PassThrough } from 'stream'
import { pipeline } from 'stream/promises'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { asyncTimeoutGuard } from '../../../../utils/timing'
import { ObjectStorage } from '../../../services/object_storage'
import { IncomingRecordingMessage } from '../types'
import { convertToPersistedMessage, maxDefined, minDefined, now } from '../utils'

const BUCKETS_LINES_WRITTEN = [0, 10, 50, 100, 500, 1000, 2000, 5000, 10000, Infinity]
export const BUCKETS_KB_WRITTEN = [0, 128, 512, 1024, 5120, 10240, 20480, 51200, 102400, 204800, Infinity]
const S3_UPLOAD_WARN_TIME_SECONDS = 2 * 60 * 1000

// NOTE: To remove once released
const metricPrefix = 'v3_'

export const FILE_EXTENSION = '.jsonl'
export const BUFFER_FILE_NAME = `buffer${FILE_EXTENSION}`
export const FLUSH_FILE_EXTENSION = `.flush${FILE_EXTENSION}`

const counterS3FilesWritten = new Counter({
    name: metricPrefix + 'recording_s3_files_written',
    help: 'A single file flushed to S3',
    labelNames: ['flushReason'],
})

const counterS3WriteErrored = new Counter({
    name: metricPrefix + 'recording_s3_write_errored',
    help: 'Indicates that we failed to flush to S3 without recovering',
})

const histogramS3LinesWritten = new Histogram({
    name: metricPrefix + 'recording_s3_lines_written_histogram',
    help: 'The number of lines in a file we send to s3',
    buckets: BUCKETS_LINES_WRITTEN,
})

const histogramS3KbWritten = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_s3_kb_written',
    help: 'The uncompressed size of file we send to S3',
    buckets: BUCKETS_KB_WRITTEN,
})

const histogramSessionAgeSeconds = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_session_age_seconds',
    help: 'The age of current sessions in seconds',
    buckets: [0, 60, 60 * 2, 60 * 5, 60 * 8, 60 * 10, 60 * 12, 60 * 15, 60 * 20, Infinity],
})

const histogramSessionSizeKb = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_session_size_kb',
    help: 'The size of current sessions in kb',
    buckets: BUCKETS_KB_WRITTEN,
})

const histogramFlushTimeSeconds = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_session_flush_time_seconds',
    help: 'The time taken to flush a session in seconds',
    buckets: [0, 2, 5, 10, 20, 30, 60, 120, 180, 300, Infinity],
})

const histogramSessionSize = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_session_lines',
    help: 'The size of sessions in numbers of lines',
    buckets: BUCKETS_LINES_WRITTEN,
})

const writeStreamBlocked = new Counter({
    name: metricPrefix + 'recording_blob_ingestion_write_stream_blocked',
    help: 'Number of times we get blocked by the stream backpressure',
})

const histogramBackpressureBlockedSeconds = new Histogram({
    name: metricPrefix + 'recording_blob_ingestion_backpressure_blocked_seconds',
    help: 'The time taken to flush a session in seconds',
    buckets: [0, 2, 5, 10, 20, 30, 60, 120, 180, 300, Infinity],
})

export type SessionManagerBufferContext = {
    sizeEstimate: number
    count: number
    eventsRange: {
        firstTimestamp: number
        lastTimestamp: number
    } | null
    createdAt: number
}

export type SessionBuffer = {
    context: SessionManagerBufferContext
    fileStream: WriteStream
}

// Context that is updated and persisted to disk so must be serializable
export type SessionManagerContext = {
    dir: string
    sessionId: string
    teamId: number
    partition: number
}

export class SessionManagerV3 {
    buffer?: SessionBuffer
    flushPromise?: Promise<void>
    destroying = false
    inProgressUpload: Upload | null = null
    flushJitterMultiplier: number

    readonly setupPromise: Promise<void>

    constructor(
        public readonly serverConfig: PluginsServerConfig,
        public readonly s3Client: ObjectStorage['s3'],
        public readonly context: SessionManagerContext
    ) {
        // We add a jitter multiplier to the buffer age so that we don't have all sessions flush at the same time
        this.flushJitterMultiplier = 1 - Math.random() * serverConfig.SESSION_RECORDING_BUFFER_AGE_JITTER
        this.setupPromise = this.setup()
    }

    private file(name: string): string {
        return path.join(this.context.dir, name)
    }

    private async setup(): Promise<void> {
        await mkdir(this.context.dir, { recursive: true })

        try {
            const fileExists = await stat(this.file('metadata.json')).then(
                () => true,
                () => false
            )
            if (fileExists) {
                const bufferMetadata: SessionManagerBufferContext = JSON.parse(
                    await readFile(this.file('metadata.json'), 'utf-8')
                )
                this.buffer = {
                    context: bufferMetadata,
                    fileStream: this.createFileStreamFor(path.join(this.context.dir, BUFFER_FILE_NAME)),
                }
            }
        } catch (error) {
            // Indicates no buffer metadata file or it's corrupted
            status.error('🧨', '[session-manager] failed to read buffer metadata', {
                ...this.context,
                error,
            })
        }

        status.info('📦', '[session-manager] started new manager', {
            ...this.context,
            ...(this.buffer?.context ?? {}),
        })
    }

    private async syncMetadata(): Promise<void> {
        if (this.buffer) {
            await writeFile(this.file('metadata.json'), JSON.stringify(this.buffer?.context), 'utf-8')
        } else {
            await unlink(this.file('metadata.json'))
        }
    }

    private async getFlushFiles(): Promise<string[]> {
        return (await readdir(this.context.dir)).filter((file) => file.endsWith(FLUSH_FILE_EXTENSION))
    }

    private captureException(error: Error, extra: Record<string, any> = {}): void {
        captureException(error, {
            extra: { ...this.context, ...extra },
            tags: { teamId: this.context.teamId, sessionId: this.context.sessionId },
        })
    }

    private captureMessage(message: string, extra: Record<string, any> = {}): void {
        const context = this.context
        captureMessage(message, {
            extra: { ...context, ...extra },
            tags: { teamId: context.teamId, sessionId: context.sessionId },
        })
    }

    public async add(message: IncomingRecordingMessage): Promise<void> {
        if (this.destroying) {
            return
        }

        await this.setupPromise

        try {
            const buffer = this.getOrCreateBuffer()
            const messageData = convertToPersistedMessage(message)
            const start = message.events.at(0)?.timestamp
            const end = message.events.at(-1)?.timestamp ?? start

            if (!start || !end) {
                captureMessage("[session-manager]: can't set events range from message without events summary", {
                    extra: { message },
                })
                return
            }

            buffer.context.eventsRange = {
                firstTimestamp: minDefined(start, buffer.context.eventsRange?.firstTimestamp) ?? start,
                lastTimestamp: maxDefined(end, buffer.context.eventsRange?.lastTimestamp) ?? end,
            }

            const content = JSON.stringify(messageData) + '\n'
            buffer.context.count += 1
            buffer.context.sizeEstimate += content.length

            if (!buffer.fileStream.write(content, 'utf-8')) {
                writeStreamBlocked.inc()

                const stopTimer = histogramBackpressureBlockedSeconds.startTimer()
                await new Promise((r) => buffer.fileStream.once('drain', r))
                stopTimer()
            }

            await this.syncMetadata()
        } catch (error) {
            this.captureException(error, { message })
            throw error
        }
    }

    public async isEmpty(): Promise<boolean> {
        return !this.buffer?.context.count && !(await this.getFlushFiles()).length
    }

    public async flush(force = false): Promise<void> {
        if (this.destroying) {
            return
        }

        await this.setupPromise

        if (!force) {
            await this.maybeFlushCurrentBuffer()
        } else {
            // This is mostly used by tests
            await this.markCurrentBufferForFlush('rebalance')
        }

        await this.flushFiles()
    }

    private async maybeFlushCurrentBuffer(): Promise<void> {
        if (!this.buffer) {
            return
        }

        if (this.buffer.context.sizeEstimate >= this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB * 1024) {
            return this.markCurrentBufferForFlush('buffer_size')
        }

        const flushThresholdMs = this.serverConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000
        const flushThresholdJitteredMs = flushThresholdMs * this.flushJitterMultiplier

        const logContext: Record<string, any> = {
            ...this.context,
            flushThresholdMs,
            flushThresholdJitteredMs,
        }

        if (!this.buffer.context.count) {
            status.warn('🚽', `[session-manager] buffer has no items yet`, { logContext })
            return
        }

        const bufferAgeInMemoryMs = now() - this.buffer.context.createdAt

        // check the in-memory age against a larger value than the flush threshold,
        // otherwise we'll flap between reasons for flushing when close to real-time processing
        const isSessionAgeOverThreshold = bufferAgeInMemoryMs >= flushThresholdJitteredMs

        logContext['bufferAgeInMemoryMs'] = bufferAgeInMemoryMs
        logContext['isSessionAgeOverThreshold'] = isSessionAgeOverThreshold

        histogramSessionAgeSeconds.observe(bufferAgeInMemoryMs / 1000)
        histogramSessionSize.observe(this.buffer.context.count)
        histogramSessionSizeKb.observe(this.buffer.context.sizeEstimate / 1024)

        if (isSessionAgeOverThreshold) {
            return this.markCurrentBufferForFlush('buffer_age')
        }
    }

    private async markCurrentBufferForFlush(reason: 'buffer_size' | 'buffer_age' | 'rebalance'): Promise<void> {
        const buffer = this.buffer
        if (!buffer) {
            // TODO: maybe error properly here?
            return
        }

        if (!buffer.context.eventsRange || !buffer.context.count) {
            // Indicates some issue with the buffer so we can close out
            this.buffer = undefined
            return
        }

        // ADD FLUSH METRICS HERE

        const { firstTimestamp, lastTimestamp } = buffer.context.eventsRange
        const fileName = `${firstTimestamp}-${lastTimestamp}${FLUSH_FILE_EXTENSION}`

        counterS3FilesWritten.labels(reason).inc(1)
        histogramS3LinesWritten.observe(buffer.context.count)
        histogramS3KbWritten.observe(buffer.context.sizeEstimate / 1024)

        // NOTE: We simplify everything by keeping the files as the same name for S3
        await new Promise((resolve) => buffer.fileStream.end(resolve))
        await rename(this.file(BUFFER_FILE_NAME), this.file(fileName))
        this.buffer = undefined

        await this.syncMetadata()
    }

    private async flushFiles(): Promise<void> {
        // We read all files marked for flushing and write them to S3
        const filesToFlush = await this.getFlushFiles()
        await Promise.all(filesToFlush.map((file) => this.flushFile(file)))
    }

    private async flushFile(filename: string): Promise<void> {
        status.info('🚽', '[session-manager] flushing file to S3', {
            filename,
            ...this.context,
        })
        if (this.destroying) {
            status.warn('🚽', '[session-manager] flush called but we are in a destroying state', {
                ...this.context,
            })
            return
        }

        const file = this.file(filename)

        const deleteFile = async () => {
            await stat(file)
            await unlink(file)
        }

        const endFlushTimer = histogramFlushTimeSeconds.startTimer()

        try {
            const targetFileName = filename.replace(FLUSH_FILE_EXTENSION, FILE_EXTENSION)
            const baseKey = `${this.serverConfig.SESSION_RECORDING_REMOTE_FOLDER}/team_id/${this.context.teamId}/session_id/${this.context.sessionId}`
            const dataKey = `${baseKey}/data/${targetFileName}`

            const readStream = createReadStream(file)
            const uploadStream = new PassThrough()

            // The compressed file
            pipeline(readStream, zlib.createGzip(), uploadStream).catch((error) => {
                // TODO: If this actually happens we probably want to destroy the buffer as we will be stuck...
                status.error('🧨', '[session-manager] writestream errored', {
                    ...this.context,
                    error,
                })
                this.captureException(error)
            })

            readStream.on('error', (err) => {
                // TODO: What should we do here?
                status.error('🧨', '[session-manager] readstream errored', {
                    ...this.context,
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
                    ContentType: 'application/jsonl',
                    Body: uploadStream,
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
                ...this.context,
            })
            this.captureException(error)
            counterS3WriteErrored.inc()

            throw error
        } finally {
            endFlushTimer()
            await deleteFile()
        }
    }

    private getOrCreateBuffer(): SessionBuffer {
        if (!this.buffer) {
            try {
                const context: SessionManagerBufferContext = {
                    sizeEstimate: 0,
                    count: 0,
                    eventsRange: null,
                    createdAt: now(),
                }
                const buffer: SessionBuffer = {
                    context,
                    fileStream: this.createFileStreamFor(this.file(BUFFER_FILE_NAME)),
                }

                this.buffer = buffer
            } catch (error) {
                this.captureException(error)
                throw error
            }
        }

        return this.buffer as SessionBuffer
    }

    protected createFileStreamFor(file: string): WriteStream {
        return createWriteStream(file, {
            // Opens in append mode in case it already exists
            flags: 'a',
            encoding: 'utf-8',
        })
    }

    public async stop(): Promise<void> {
        this.destroying = true
        if (this.inProgressUpload !== null) {
            await this.inProgressUpload.abort().catch((error) => {
                status.error('🧨', '[session-manager][realtime] failed to abort in progress upload', {
                    ...this.context,
                    error,
                })
                this.captureException(error)
            })
            this.inProgressUpload = null
        }

        const buffer = this.buffer
        if (buffer) {
            await new Promise((resolve) => buffer.fileStream.end(resolve))
        }

        if (await this.isEmpty()) {
            status.info('🧨', '[session-manager] removing empty session directory', {
                ...this.context,
            })

            await rmdir(this.context.dir, { recursive: true })
        }
    }
}
