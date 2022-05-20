import { PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'

const aws = require('aws-sdk')

let S3: typeof aws.S3 | null = null

export interface ObjectStorage {
    healthCheck: () => Promise<boolean>
}

export const connectObjectStorage = (serverConfig: Partial<PluginsServerConfig>): ObjectStorage => {
    let storage = {
        healthCheck: async () => {
            return Promise.resolve(false)
        },
    }
    try {
        const {
            OBJECT_STORAGE_ENDPOINT,
            OBJECT_STORAGE_ACCESS_KEY_ID,
            OBJECT_STORAGE_SECRET_ACCESS_KEY,
            OBJECT_STORAGE_ENABLED,
            OBJECT_STORAGE_BUCKET,
        } = serverConfig

        if (OBJECT_STORAGE_ENABLED && !S3) {
            S3 = new aws.S3({
                endpoint: OBJECT_STORAGE_ENDPOINT,
                accessKeyId: OBJECT_STORAGE_ACCESS_KEY_ID,
                secretAccessKey: OBJECT_STORAGE_SECRET_ACCESS_KEY,
                s3ForcePathStyle: true, // needed with minio?
                signatureVersion: 'v4',
            })
        }

        storage = {
            healthCheck: async () => {
                if (!OBJECT_STORAGE_BUCKET) {
                    status.error('😢', 'No object storage bucket configured')
                    return false
                }

                try {
                    await S3.headBucket({
                        Bucket: OBJECT_STORAGE_BUCKET,
                    }).promise()
                    return true
                } catch (error) {
                    return false
                }
            },
        }
    } catch (e) {
        status.warn('😢', `could not initialise storage: ${e}`)
    }

    return storage
}
