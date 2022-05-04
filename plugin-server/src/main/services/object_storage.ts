import { PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'

const aws = require('aws-sdk')

let S3: typeof aws.S3 | null = null

export interface ObjectStorage {
    isEnabled: boolean
    putObject: (params: { Bucket: string; Body: any; Key: string }, cb: (err: any, resp: any) => void) => void
    healthCheck: () => Promise<boolean>
}

export const connectObjectStorage = (serverConfig: Partial<PluginsServerConfig>): ObjectStorage => {
    const {
        OBJECT_STORAGE_HOST,
        OBJECT_STORAGE_PORT,
        OBJECT_STORAGE_ACCESS_KEY_ID,
        OBJECT_STORAGE_SECRET_ACCESS_KEY,
        OBJECT_STORAGE_ENABLED,
        OBJECT_STORAGE_BUCKET,
    } = serverConfig

    if (OBJECT_STORAGE_ENABLED && !S3) {
        S3 = new aws.S3({
            endpoint: `http://${OBJECT_STORAGE_HOST}:${OBJECT_STORAGE_PORT}`,
            accessKeyId: OBJECT_STORAGE_ACCESS_KEY_ID,
            secretAccessKey: OBJECT_STORAGE_SECRET_ACCESS_KEY,
            s3ForcePathStyle: true, // needed with minio?
            signatureVersion: 'v4',
        })
    }

    return {
        isEnabled: !!OBJECT_STORAGE_ENABLED,
        putObject: OBJECT_STORAGE_ENABLED ? (params, callback) => S3.putObject(params, callback) : () => ({}),
        healthCheck: async () => {
            if (!OBJECT_STORAGE_BUCKET) {
                status.error('😢', 'No object storage bucket configured')
                return false
            }

            try {
                const listBucketsResponse = await S3.listBuckets().promise()
                const buckets: string[] = (listBucketsResponse?.Buckets || []).map(
                    (bucketResponse: { Name: string }) => bucketResponse.Name
                )
                status.info(
                    '🪣',
                    `read ${buckets.length} ${
                        buckets.length === 1 ? 'bucket' : 'buckets'
                    } from storage: ${buckets.join()}`
                )
                return buckets.includes(OBJECT_STORAGE_BUCKET)
            } catch (error) {
                if (error.statusCode === 404) {
                    return false
                }
                throw error
            }
        },
    }
}
