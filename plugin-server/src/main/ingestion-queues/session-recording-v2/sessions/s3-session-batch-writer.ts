import { CompleteMultipartUploadCommandOutput, HeadBucketCommand, S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { randomBytes } from 'crypto'
import { PassThrough } from 'stream'

import { status } from '../../../../utils/status'
import { SessionBatchFileStorage, SessionBatchFileWriter, WriteSessionResult } from './session-batch-file-storage'

class S3SessionBatchFileWriter implements SessionBatchFileWriter {
    private stream: PassThrough
    private uploadPromise: Promise<CompleteMultipartUploadCommandOutput>
    private key: string
    private currentOffset = 0
    private timeoutId: NodeJS.Timeout | null = null
    private error: Error | null = null
    private rejectCallbacks: ((error: Error) => void)[] = []

    constructor(
        private readonly s3: S3Client,
        private readonly bucket: string,
        private readonly prefix: string,
        private readonly timeout: number = 5000 // Default 5 second timeout
    ) {
        this.stream = new PassThrough()
        this.key = this.generateKey()

        status.debug('🔄', 's3_session_batch_writer_opening_stream', { key: this.key })

        const upload = new Upload({
            client: this.s3,
            params: {
                Bucket: this.bucket,
                Key: this.key,
                Body: this.stream,
                ContentType: 'application/octet-stream',
            },
        })

        // Handle stream errors
        this.stream.on('error', (error) => {
            this.handleError(error)
        })

        // Add timeout
        this.timeoutId = setTimeout(() => {
            this.handleError(new Error(`S3 upload timed out after ${this.timeout}ms`))
            this.stream.destroy()
        }, this.timeout)

        // Handle upload errors
        this.uploadPromise = upload.done().catch((error) => {
            status.error('🔄', 's3_session_batch_writer_upload_error', { key: this.key, error })
            this.handleError(error)
            throw error
        })
    }

    private handleError(error: Error): void {
        if (!this.error) {
            this.error = error
            // Call all rejection callbacks
            this.rejectCallbacks.forEach((reject) => reject(error))
            this.rejectCallbacks = [] // Clear the list
        }
    }

    private async withErrorHandling<T>(operation: () => Promise<T>): Promise<T> {
        // If we already have an error, reject immediately
        if (this.error) {
            throw this.error
        }

        // Create a promise that will reject if an error occurs
        const errorPromise = new Promise<T>((_, reject) => {
            this.rejectCallbacks.push(reject)
        })

        try {
            // Race between the operation and potential errors
            return await Promise.race([operation(), errorPromise])
        } finally {
            // Remove the rejection callback
            this.rejectCallbacks = this.rejectCallbacks.filter((cb) => !this.rejectCallbacks.includes(cb))
        }
    }

    public async writeSession(buffer: Buffer): Promise<WriteSessionResult> {
        return await this.withErrorHandling(async () => {
            const startOffset = this.currentOffset

            // Write and handle backpressure
            const canWriteMore = this.stream.write(buffer)
            if (!canWriteMore) {
                await new Promise<void>((resolve) => {
                    this.stream.once('drain', resolve)
                })
            }

            this.currentOffset += buffer.length

            return {
                bytesWritten: buffer.length,
                url: `s3://${this.bucket}/${this.key}?range=bytes=${startOffset}-${this.currentOffset - 1}`,
            }
        })
    }

    public async finish(): Promise<void> {
        return await this.withErrorHandling(async () => {
            try {
                this.stream.end()
                await this.uploadPromise
                if (this.timeoutId) {
                    clearTimeout(this.timeoutId)
                }
            } catch (error) {
                status.error('🔄', 's3_session_batch_writer_upload_error', { key: this.key, error })
                throw error
            }
        })
    }

    private generateKey(): string {
        const timestamp = Date.now()
        const suffix = randomBytes(8).toString('hex')
        return `${this.prefix}/${timestamp}-${suffix}`
    }
}

export class S3SessionBatchFileStorage implements SessionBatchFileStorage {
    constructor(
        private readonly s3: S3Client,
        private readonly bucket: string,
        private readonly prefix: string,
        private readonly timeout: number = 5000
    ) {
        status.debug('🔁', 's3_session_batch_writer_created', { bucket, prefix })
    }

    public newBatch(): SessionBatchFileWriter {
        return new S3SessionBatchFileWriter(this.s3, this.bucket, this.prefix, this.timeout)
    }

    public async checkHealth(): Promise<boolean> {
        try {
            const command = new HeadBucketCommand({ Bucket: this.bucket })
            await this.s3.send(command)
            return true
        } catch (error) {
            status.error('🔁', 's3_session_batch_writer_healthcheck_error', {
                bucket: this.bucket,
                error,
            })
            return false
        }
    }
}
