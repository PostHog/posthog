import { randomUUID } from 'crypto'
import { createReadStream, mkdirSync, writeFileSync } from 'fs'
import { appendFile, rm } from 'fs/promises'
import path from 'path'
import { Counter } from 'prom-client'
import * as zlib from 'zlib'

import { status } from '../../../../utils/status'
import { ObjectStorage } from '../../../services/object_storage'
import { config } from './config'
import { IncomingRecordingMessage } from './types'
import { convertToPersistedMessage } from './utils'

export const counterS3FilesWritten = new Counter({
    name: 'recording_s3_files_written',
    help: 'Indicates that a given key has overflowed capacity and been redirected to a different topic. Value incremented once a minute.',
    labelNames: ['partition_key'],
})

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
    chunks: Map<string, IncomingRecordingMessage[]> = new Map()
    buffer: SessionBuffer
    flushBuffer?: SessionBuffer

    constructor(
        public readonly objectStorage: ObjectStorage['s3'],
        public readonly teamId: number,
        public readonly sessionId: string,
        public readonly partition: number,
        public readonly topic: string,
        private readonly onFinish: (offsetsToRemove: number[]) => void
    ) {
        this.buffer = this.createBuffer()
    }

    public async add(message: IncomingRecordingMessage): Promise<void> {
        if (message.chunk_count === 1) {
            await this.addToBuffer(message)
        } else {
            await this.addToChunks(message)
        }

        const capacity = this.buffer.size / (config.sessions.maxEventGroupKb * 1024)
        status.info(
            `Buffer ${this.sessionId}:: capacity: ${(capacity * 100).toFixed(2)}% count: ${
                this.buffer.count
            } ${Math.round(this.buffer.size / 1024)}KB chunks: ${this.chunks.size})`
        )

        const shouldFlush =
            capacity > 1 ||
            Date.now() - this.buffer.createdAt.getTime() >= config.sessions.maxEventGroupAgeSeconds * 1000

        if (shouldFlush) {
            status.info(`Flushing buffer ${this.sessionId}...`)
            await this.flush()
        }
    }

    public get isEmpty(): boolean {
        return this.buffer.count === 0 && this.chunks.size === 0
    }

    /**
     * Flushing takes the current buffered file and moves it to the flush buffer
     * We then attempt to write the events to S3 and if successful, we clear the flush buffer
     */
    public async flush(): Promise<void> {
        if (this.flushBuffer) {
            status.warn("Flush called but we're already flushing")
            return
        }
        // We move the buffer to the flush buffer and create a new buffer so that we can safely write the buffer to disk
        this.flushBuffer = this.buffer
        this.buffer = this.createBuffer()

        try {
            const baseKey = `${config.s3.sessionRecordingFolder}/team_id/${this.teamId}/session_id/${this.sessionId}`
            const dataKey = `${baseKey}/data/${this.flushBuffer.createdAt.getTime()}` // TODO: Change to be based on events times

            // TODO should only compress over some threshold? Depends how many uncompressed files we see below c200kb
            const fileStream = createReadStream(this.flushBuffer.file).pipe(zlib.createGzip())

            const parallelUploads3 = new Upload({
                client: s3Client,
                params: {
                    Bucket: config.s3.bucket,
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
            file: path.join(config.sessions.directory, `${this.teamId}.${this.sessionId}.${id}.jsonl`),
            offsets: [],
        }

        // NOTE: We should move this to do once on startup
        mkdirSync(config.sessions.directory, { recursive: true })
        // NOTE: We may want to figure out how to safely do this async
        writeFileSync(this.buffer.file, '', 'utf-8')

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
        this.onFinish([])

        return Promise.resolve()
    }
}
