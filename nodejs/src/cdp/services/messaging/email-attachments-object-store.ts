import { DeleteObjectsCommand, GetObjectCommand, NoSuchKey, PutObjectCommand, S3Client } from '@aws-sdk/client-s3'

export interface EmailAttachmentObjectStore {
    put(key: string, content: Buffer): Promise<void>
    /** Resolves to null when no object has this key. */
    get(key: string): Promise<Buffer | null>
    delete(keys: string[]): Promise<void>
}

export interface EmailAttachmentObjectStoreConfig {
    CDP_EMAIL_ATTACHMENTS_S3_BUCKET: string
    CDP_EMAIL_ATTACHMENTS_S3_REGION: string
    CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT: string
    CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID: string
    CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY: string
}

const S3_DELETE_BATCH_SIZE = 1000

class S3EmailAttachmentObjectStore implements EmailAttachmentObjectStore {
    constructor(
        private readonly client: S3Client,
        private readonly bucket: string
    ) {}

    public async put(key: string, content: Buffer): Promise<void> {
        await this.client.send(new PutObjectCommand({ Bucket: this.bucket, Key: key, Body: content }))
    }

    public async get(key: string): Promise<Buffer | null> {
        try {
            const response = await this.client.send(new GetObjectCommand({ Bucket: this.bucket, Key: key }))
            return response.Body ? Buffer.from(await response.Body.transformToByteArray()) : null
        } catch (error) {
            if (error instanceof NoSuchKey) {
                return null
            }
            throw error
        }
    }

    public async delete(keys: string[]): Promise<void> {
        for (let start = 0; start < keys.length; start += S3_DELETE_BATCH_SIZE) {
            const batch = keys.slice(start, start + S3_DELETE_BATCH_SIZE)
            await this.client.send(
                new DeleteObjectsCommand({
                    Bucket: this.bucket,
                    Delete: { Objects: batch.map((Key) => ({ Key })), Quiet: true },
                })
            )
        }
    }
}

/** Null when no bucket is configured, which keeps attachments in Postgres at the smaller size limit. */
export function buildEmailAttachmentObjectStore(
    config: EmailAttachmentObjectStoreConfig
): EmailAttachmentObjectStore | null {
    if (!config.CDP_EMAIL_ATTACHMENTS_S3_BUCKET) {
        return null
    }
    const hasKeys = config.CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID && config.CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY
    const client = new S3Client({
        region: config.CDP_EMAIL_ATTACHMENTS_S3_REGION,
        ...(config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT && {
            endpoint: config.CDP_EMAIL_ATTACHMENTS_S3_ENDPOINT,
            forcePathStyle: true,
        }),
        ...(hasKeys && {
            credentials: {
                accessKeyId: config.CDP_EMAIL_ATTACHMENTS_S3_ACCESS_KEY_ID,
                secretAccessKey: config.CDP_EMAIL_ATTACHMENTS_S3_SECRET_ACCESS_KEY,
            },
        }),
    })
    return new S3EmailAttachmentObjectStore(client, config.CDP_EMAIL_ATTACHMENTS_S3_BUCKET)
}
