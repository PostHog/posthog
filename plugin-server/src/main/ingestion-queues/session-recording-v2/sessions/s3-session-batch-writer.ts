import { CompleteMultipartUploadCommandOutput, S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { randomBytes } from 'crypto'
import { PassThrough } from 'stream'

import { status } from '../../../../utils/status'
import { SessionBatchFileStorage, SessionBatchFileWriter, WriteSessionResult } from './session-batch-file-storage'

class S3SessionBatchFileWriter implements SessionBatchFileWriter {
    private stream: PassThrough
    private uploadPromise: Promise<CompleteMultipartUploadCommandOutput>
    private writeError: Promise<never>
    private key: string
    private currentOffset = 0

    constructor(private readonly s3: S3Client, private readonly bucket: string, private readonly prefix: string) {
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

        this.writeError = new Promise((_, reject) => {
            this.stream.on('error', reject)
        })

        // This doesn't mean the upload is done 🙃
        // We need to call `done` to allow the stream to be drained.
        // Once the stream is ended, the upload will complete and the promise will resolve.
        this.uploadPromise = upload.done()
    }

    public async writeSession(buffer: Buffer): Promise<WriteSessionResult> {
        const startOffset = this.currentOffset

        // Write and handle backpressure, but also watch for errors
        const canWriteMore = this.stream.write(buffer)
        if (!canWriteMore) {
            await Promise.race([
                new Promise<void>((resolve) => {
                    this.stream.once('drain', resolve)
                }),
                this.writeError,
            ])
        }

        this.currentOffset += buffer.length

        return {
            bytesWritten: buffer.length,
            url: `s3://${this.bucket}/${this.key}?range=bytes=${startOffset}-${this.currentOffset - 1}`,
        }
    }

    public async finish(): Promise<void> {
        status.debug('🔄', 's3_session_batch_writer_finishing_stream', { key: this.key })
        try {
            this.stream.end()
            await this.uploadPromise
            status.info('🔄', 's3_session_batch_writer_upload_complete', { key: this.key })
        } catch (error) {
            status.error('🔄', 's3_session_batch_writer_upload_error', { key: this.key, error })
            throw error
        }
    }

    private generateKey(): string {
        const timestamp = Date.now()
        const suffix = randomBytes(8).toString('hex')
        return `${this.prefix}/${timestamp}-${suffix}`
    }
}

export class S3SessionBatchFileStorage implements SessionBatchFileStorage {
    constructor(private readonly s3: S3Client, private readonly bucket: string, private readonly prefix: string) {
        status.debug('🔁', 's3_session_batch_writer_created', { bucket, prefix })
    }

    public newBatch(): SessionBatchFileWriter {
        return new S3SessionBatchFileWriter(this.s3, this.bucket, this.prefix)
    }
}
