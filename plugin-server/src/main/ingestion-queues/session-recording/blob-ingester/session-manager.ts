import { Upload } from '@aws-sdk/lib-storage'
import { captureException } from '@sentry/node'
import { randomUUID } from 'crypto'
import { createReadStream, writeFileSync } from 'fs'
import { appendFile, unlink } from 'fs/promises'
import path from 'path'
import { Counter } from 'prom-client'
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
})

export const counterS3WriteErrored = new Counter({
    name: 'recording_s3_write_errored',
    help: 'Indicates that we failed to flush to S3 without recovering',
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

async function deleteFile(file: string) {
    try {
        await unlink(file)
    } catch (err) {
        if (err && err.code === 'ENOENT') {
            status.warn('⚠️', 'blob_ingester_session_manager failed deleting file ' + file + ', file not found', {
                err,
                file,
            })
            return
        }
        status.error('🧨', 'blob_ingester_session_manager failed deleting file ' + file, { err, file })
        captureException(err)
        throw err
    }
}

export class SessionManager {
    chunks: Map<string, IncomingRecordingMessage[]> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer

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

        await this.flushIfNecessary()
    }

    public get isEmpty(): boolean {
        return this.buffer.count === 0 && this.chunks.size === 0
    }

    public async flushIfNecessary(): Promise<void> {
        const bufferSizeKb = this.buffer.size / 1024
        const gzipSizeKb = bufferSizeKb * ESTIMATED_GZIP_COMPRESSION_RATIO
        const gzippedCapacity = gzipSizeKb / this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB

        const overCapacity = gzippedCapacity > 1
        const timeSinceLastFlushTooLong =
            Date.now() - this.buffer.createdAt.getTime() >=
            this.serverConfig.SESSION_RECORDING_MAX_BUFFER_AGE_SECONDS * 1000
        const readyToFlush = overCapacity || timeSinceLastFlushTooLong

        if (readyToFlush) {
            await this.flush()
        }
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(): Promise<void> {
        if (this.flushBuffer) {
            status.warn('⚠️', "blob_ingester_session_manager Flush called but we're already flushing")
            return
        }

        const bufferSizeKb = this.buffer.size / 1024
        const gzipSizeKb = bufferSizeKb * ESTIMATED_GZIP_COMPRESSION_RATIO
        const gzippedCapacity = gzipSizeKb / this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB
        status.info('🚽', `blob_ingester_session_manager flushing buffer ${this.sessionId}`, {
            sizeInBufferKB: bufferSizeKb,
            chunksSize: this.chunks.size,
            estimatedSizeInGzipKB: Math.round(gzipSizeKb),
            bufferThreshold: this.serverConfig.SESSION_RECORDING_MAX_BUFFER_SIZE_KB,
            calculatedCapacity: gzippedCapacity,
            percentageCapacityUsed: (gzippedCapacity * 100).toFixed(2),
            count: this.buffer.count,
            sessionId: this.sessionId,
        })

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
            })
            await parallelUploads3.done()

            counterS3FilesWritten.inc(1)
            status.info('🚽', `blob_ingester_session_manager Flushed buffer ${this.sessionId}`)
        } catch (error) {
            // TODO: If we fail to write to S3 we should be do something about it
            status.error('🧨', 'blob_ingester_session_manager failed writing session recording blob to S3', error)
            captureException(error)
            counterS3WriteErrored.inc()
        } finally {
            await deleteFile(this.flushBuffer.file)

            const offsets = this.flushBuffer.offsets
            this.flushBuffer = undefined

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
                bufferFileDir(this.serverConfig.SESSION_RECORDING_LOCAL_DIRECTORY),
                `${this.teamId}.${this.sessionId}.${id}.jsonl`
            ),
            offsets: [],
        }

        // NOTE: We can't do this easily async as we would need to handle the race condition of multiple events coming in at once.
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

        try {
            await appendFile(this.buffer.file, content, 'utf-8')
        } catch (e) {
            status.error('🧨', 'blob_ingester_session_manager failed writing session recording buffer to disk', e)
            captureException(e)
            throw e
        }
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
        status.debug('␡', `blob_ingester_session_manager Destroying session manager ${this.sessionId}`)
        const filePromises: Promise<void>[] = [this.flushBuffer?.file, this.buffer.file]
            .filter((x): x is string => x !== undefined)
            .map((x) => deleteFile(x))
        await Promise.all(filePromises)
    }
}
