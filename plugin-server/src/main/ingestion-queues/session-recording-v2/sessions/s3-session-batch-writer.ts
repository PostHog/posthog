import { CompleteMultipartUploadCommandOutput, HeadBucketCommand, S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { randomBytes } from 'crypto'
import { PassThrough } from 'stream'

import { logger } from '../../../../utils/logger'
import { SessionBatchMetrics } from './metrics'
import {
    SessionBatchFileStorage,
    SessionBatchFileWriter,
    WriteSessionData,
    WriteSessionResult,
} from './session-batch-file-storage'

class S3SessionBatchFileWriter implements SessionBatchFileWriter {
    private stream: PassThrough
    private uploadPromise: Promise<CompleteMultipartUploadCommandOutput>
    private key: string
    private currentOffset = 0
    private timeoutId: NodeJS.Timeout | null = null
    private error: Error | null = null
    private rejectCallbacks: ((error: Error) => void)[] = []
    private uploadStartTime: number

    constructor(
        private readonly s3: S3Client,
        private readonly bucket: string,
        private readonly prefix: string,
        private readonly timeout: number
    ) {
        this.stream = new PassThrough()
        this.key = this.generateKey()
        this.uploadStartTime = Date.now()

        logger.debug('🔄', 's3_session_batch_writer_opening_stream', { key: this.key })

        SessionBatchMetrics.incrementS3BatchesStarted()

        const upload = new Upload({
            client: this.s3,
            params: {
                Bucket: this.bucket,
                Key: this.key,
                Body: this.stream,
                ContentType: 'application/octet-stream',
            },
        })

        this.stream.on('error', (error) => {
            logger.error('🔄', 's3_session_batch_writer_stream_error', { key: this.key, error })
            SessionBatchMetrics.incrementS3UploadErrors()
            this.handleError(error)
        })

        this.timeoutId = setTimeout(() => {
            this.handleError(new Error(`S3 upload timed out after ${this.timeout}ms`))
            SessionBatchMetrics.incrementS3UploadTimeouts()
            this.stream.destroy()
        }, this.timeout)

        this.uploadPromise = upload.done().catch((error) => {
            logger.error('🔄', 's3_session_batch_writer_upload_error', { key: this.key, error })
            SessionBatchMetrics.incrementS3UploadErrors()
            this.handleError(error)
            throw error
        })
    }

    private handleError(error: Error): void {
        if (!this.error) {
            this.error = error
            this.rejectCallbacks.forEach((reject) => reject(error))
            this.rejectCallbacks = []
            if (this.timeoutId) {
                clearTimeout(this.timeoutId)
                this.timeoutId = null
            }
        }
    }

    private async withErrorBarrier<T>(operation: () => Promise<T>): Promise<T> {
        return new Promise<T>((resolve, reject) => {
            if (this.error) {
                reject(this.error)
                return
            }

            this.rejectCallbacks.push(reject)

            operation()
                .then((result) => {
                    // If the error was set, it means that the reject has already been called
                    // and collected from the list. See handleError for more details.
                    if (!this.error) {
                        // Cleanup is not strictly necessary, as calling reject after resolve has no effect,
                        // but it's better to keep the list clean.
                        this.rejectCallbacks = this.rejectCallbacks.filter((cb) => cb !== reject)
                        resolve(result)
                    }
                })
                .catch((error) => {
                    // Defer to the common error handling code, it will call reject if necessary.
                    logger.error('🔄', 's3_session_batch_writer_operation_error', { key: this.key, error })
                    SessionBatchMetrics.incrementS3UploadErrors()
                    this.handleError(error)
                })
        })
    }

    public async writeSession(sessionData: WriteSessionData): Promise<WriteSessionResult> {
        return await this.withErrorBarrier(async () => {
            const buffer = sessionData.buffer
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
                retentionPeriodDays: null,
            }
        })
    }

    public async finish(): Promise<void> {
        return await this.withErrorBarrier(async () => {
            try {
                this.stream.end()
                await this.uploadPromise
                if (this.timeoutId) {
                    clearTimeout(this.timeoutId)
                    this.timeoutId = null
                }

                // Record successful upload metrics
                const uploadDuration = (Date.now() - this.uploadStartTime) / 1000
                SessionBatchMetrics.incrementS3BatchesUploaded()
                SessionBatchMetrics.observeS3UploadLatency(uploadDuration)
                SessionBatchMetrics.incrementS3BytesWritten(this.currentOffset)
            } catch (error) {
                logger.error('🔄', 's3_session_batch_writer_upload_error', { key: this.key, error })
                SessionBatchMetrics.incrementS3UploadErrors()
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
        logger.debug('🔁', 's3_session_batch_writer_created', { bucket, prefix })
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
            logger.error('🔁', 's3_session_batch_writer_healthcheck_error', {
                bucket: this.bucket,
                error,
            })
            return false
        }
    }
}
