import { S3Client } from '@aws-sdk/client-s3'
import { Upload } from '@aws-sdk/lib-storage'
import { randomBytes } from 'crypto'
import { PassThrough } from 'stream'

import { status } from '../../../../utils/status'
import { SessionBatchFileWriter, StreamWithFinish } from './session-batch-file-writer'

/**
 * Writes session batch files to S3
 */
export class S3SessionBatchWriter implements SessionBatchFileWriter {
    constructor(private readonly s3: S3Client, private readonly bucket: string, private readonly prefix: string) {
        status.info('🔄', 's3_session_batch_writer_created', { bucket: this.bucket, prefix: this.prefix })
    }

    public newBatch(): StreamWithFinish {
        const passThrough = new PassThrough()
        const key = this.generateKey()

        status.debug('🔄', 's3_session_batch_writer_opening_stream', { key })

        const upload = new Upload({
            client: this.s3,
            params: {
                Bucket: this.bucket,
                Key: key,
                Body: passThrough,
                ContentType: 'application/octet-stream',
            },
        })

        return {
            stream: passThrough,
            finish: async () => {
                status.debug('🔄', 's3_session_batch_writer_finishing_stream', { key })
                passThrough.end()
                try {
                    await upload.done()
                    status.info('🔄', 's3_session_batch_writer_upload_complete', { key })
                } catch (error) {
                    status.error('🔄', 's3_session_batch_writer_upload_error', { key, error })
                    throw error
                }
            },
        }
    }

    private generateKey(): string {
        const timestamp = Date.now()
        const suffix = randomBytes(8).toString('hex')
        return `${this.prefix}/${timestamp}-${suffix}`
    }
}
