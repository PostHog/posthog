import { Upload } from '@aws-sdk/lib-storage'
import { randomUUID } from 'crypto'
import { createReadStream, mkdirSync, writeFileSync } from 'fs'
import { appendFile, rm } from 'fs/promises'
import path from 'path'
import { Counter } from 'prom-client'
import * as zlib from 'zlib'

import { PluginsServerConfig } from '../../../../types'
import { status } from '../../../../utils/status'
import { ObjectStorage } from '../../../services/object_storage'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage } from './utils'

export const counterS3FilesWritten = new Counter({
    name: 'recording_s3_files_written',
    help: 'Indicates that a given key has overflowed capacity and been redirected to a different topic. Value incremented once a minute.',
    labelNames: ['partition_key'],
})

const ESTIMATED_GZIP_COMPRESSION_RATIO = 0.1

// The buffer is a list of messages grouped
type SessionBuffer = {
    id: string
    count: number
    size: number
    createdAt: Date
    file: string
    offsets: number[]
}

export class SessionManager {
    get flushingPaused(): boolean {
        return this._flushingPaused
    }

    chunks: Map<string, IncomingRecordingMessage[]> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer
    private _flushingPaused = false

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

    public async add(message: IncomingRecordingMessage): Promise<void> {
        // TODO: Check that the offset is higher than the lastProcessed
        // If not - ignore it
        // If it is - update lastProcessed and process it
        if (message.chunk_count === 1) {
            await this.addToBuffer(message)
        } else {
            await this.addToChunks(message)
        }

        await this.flushIfNeccessary(true)
    }

    public get isEmpty(): boolean {
        return this.buffer.count === 0 && this.chunks.size === 0
    }

    public pauseFlushing() {
        status.info('🚽', `Pausing flushing for buffer ${this.sessionId}...`)
        this._flushingPaused = true
    }

    public resumeFlushing() {
        status.info('🚽', `Resuming flushing for buffer ${this.sessionId}...`)
        this._flushingPaused = false
    }

    public async flushIfNeccessary(shouldLog = false): Promise<void> {
        const bufferSizeKb = this.buffer.size / 1024
        const gzipSizeKb = bufferSizeKb * ESTIMATED_GZIP_COMPRESSION_RATIO
        const gzippedCapacity = gzipSizeKb / this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB

        if (shouldLog) {
            status.info(
                '🚽',
                `Buffer ${this.sessionId}:: buffer size: ${
                    this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB
                }kb capacity: ${(gzippedCapacity * 100).toFixed(2)}%: count: ${this.buffer.count} ${Math.round(
                    bufferSizeKb
                )}KB (~ ${Math.round(gzipSizeKb)}KB GZIP) chunks: ${this.chunks.size}) flushingIsPaused: ${
                    this._flushingPaused
                }`
            )
        }

        const readyToFlush =
            gzippedCapacity > 1 ||
            Date.now() - this.buffer.createdAt.getTime() >=
                this.serverConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000

        if (!this.flushingPaused && readyToFlush) {
            status.info('🚽', `Flushing buffer ${this.sessionId}...`)
            await this.flush()
        }
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(): Promise<void> {
        if (this.flushBuffer) {
            status.warn('⚠️', "Flush called but we're already flushing")
            return
        }

        if (this._flushingPaused) {
            status.warn('⚠️', 'Flush called but flushing is paused')
            return
        }

        // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
        this.flushBuffer = this.buffer
        this.buffer = this.createBuffer()

        try {
            const baseKey = `${this.serverConfig.SESSION_RECORDING_REMOTE_FOLDER}/team_id/${this.teamId}/session_id/${this.sessionId}`
            const dataKey = `${baseKey}/data/${this.flushBuffer.createdAt.getTime()}` // TODO: Change to be based on events times

            // TODO should only compress over some threshold? Depends how many uncompressed files we see below c200kb
            const fileStream = createReadStream(this.flushBuffer.file).pipe(zlib.createGzip())

            const parallelUploads3 = new Upload({
                client: this.s3Client,
                params: {
                    Bucket: this.serverConfig.OBJECT_STORAGE_BUCKET,
                    Key: dataKey,
                    Body: fileStream,
                },
                // queueSize: 4, // optional concurrency configuration
                // partSize: 1024 * 1024 * 5, // optional size of each part, in bytes, at least 5MB
                // leavePartsOnError: false, // optional manually handle dropped parts
            })
            await parallelUploads3.done()

            counterS3FilesWritten.inc(1)
            // counterS3FilesWritten.add(1, {
            //     bytes: this.flushBuffer.size, // since the file is compressed this is wrong, and we don't know the compressed size 🤔
            // })

            // TODO: Increment file count and size metric
        } catch (error) {
            // TODO: If we fail to write to S3 we should be do something about it
            status.error(error)
        } finally {
            await rm(this.flushBuffer.file)

            const offsets = this.flushBuffer.offsets
            this.flushBuffer = undefined

            status.debug('🚽', `Flushed buffer ${this.sessionId} (removing offsets: ${offsets})`)
            // TODO: Sync the last processed offset to redis
            this.onFinish(offsets)
        }
    }

    private createBuffer(): SessionBuffer {
        const id = randomUUID()
        const buffer = {
            id,
            count: 0,
            size: 0,
            createdAt: new Date(),
            file: path.join(
                this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY,
                `${this.teamId}.${this.sessionId}.${id}.jsonl`
            ),
            offsets: [],
        }

        // NOTE: We should move this to do once on startup
        mkdirSync(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY, { recursive: true })
        // NOTE: We may want to figure out how to safely do this async
        writeFileSync(buffer.file, '', 'utf-8')

        return buffer
    }

    /**
     * Full messages (all chunks) are added to the buffer directly
     */
    private async addToBuffer(message: IncomingRecordingMessage): Promise<void> {
        const content = JSON.stringify(convertToPersistedMessage(message)) + '\n'
        this.buffer.count += 1
        this.buffer.size += Buffer.byteLength(content)
        this.buffer.offsets.push(message.metadata.offset)
        await appendFile(this.buffer.file, content, 'utf-8')
    }

    /**
     * Chunked messages are added to the chunks map
     * Once all chunks are received, the message is added to the buffer
     *
     */
    private async addToChunks(message: IncomingRecordingMessage): Promise<void> {
        // If it is a chunked message we add to the collected chunks
        let chunks: IncomingRecordingMessage[] = []

        if (!this.chunks.has(message.chunk_id)) {
            this.chunks.set(message.chunk_id, chunks)
        } else {
            chunks = this.chunks.get(message.chunk_id) || []
        }

        chunks.push(message)

        if (chunks.length === message.chunk_count) {
            // We want to add all the chunk offsets as well so that they are tracked correctly
            // NOTE: Shouldn't this be outside of this if?
            chunks.forEach((x) => {
                this.buffer.offsets.push(x.metadata.offset)
            })

            // If we have all the chunks, we can add the message to the buffer
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

    public destroy(): Promise<void> {
        // TODO: Should we delete the buffer files??
        status.debug('␡', `Destroying session manager ${this.sessionId}`)
        this.onFinish([])

        return Promise.resolve()
    }
}
