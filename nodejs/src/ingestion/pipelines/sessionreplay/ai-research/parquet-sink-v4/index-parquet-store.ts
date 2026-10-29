/** Writes one v4 index file to `index/{index}/dt={day}/` in the rrweb bucket, named as the recorder names its files. */
import { PutObjectCommand, S3Client } from '@aws-sdk/client-s3'
import { randomBytes } from 'crypto'

import { V4Index, V4IndexRow } from './index-columns'
import { indexRowsToParquet } from './parquet-writer'

// A file can hold up to the sink's byte target of rows, so the upload gets more time than v3's 30 seconds.
const PUT_TIMEOUT_MS = 120_000

export function indexFileKey(index: V4Index, writeDay: string, nowMs: number): string {
    return `index/${index}/dt=${writeDay}/${nowMs}-${randomBytes(8).toString('hex')}.parquet`
}

/** A 412 means the SDK retried a PUT whose first try stored the object, so the object is there. */
function isPreconditionFailed(error: unknown): boolean {
    if (typeof error !== 'object' || error === null) {
        return false
    }
    const { $metadata, name } = error as { $metadata?: { httpStatusCode?: unknown }; name?: unknown }
    return $metadata?.httpStatusCode === 412 || name === 'PreconditionFailed'
}

export class IndexParquetStore {
    constructor(
        private readonly s3Client: S3Client,
        private readonly bucket: string,
        private readonly rowGroupSize: number
    ) {}

    public encode(index: V4Index, rows: readonly V4IndexRow[]): Promise<Buffer> {
        return indexRowsToParquet(index, rows, this.rowGroupSize)
    }

    public async put(index: V4Index, writeDay: string, body: Buffer, nowMs: number): Promise<string> {
        const key = indexFileKey(index, writeDay, nowMs)
        try {
            await this.s3Client.send(
                new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: body, IfNoneMatch: '*' }),
                { abortSignal: AbortSignal.timeout(PUT_TIMEOUT_MS) }
            )
        } catch (error) {
            if (!isPreconditionFailed(error)) {
                throw error
            }
        }
        return key
    }
}
