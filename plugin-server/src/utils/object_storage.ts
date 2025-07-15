import { HeadBucketCommand, S3Client } from '@aws-sdk/client-s3'

import { PluginsServerConfig } from '../types'
import { logger } from './logger'

export interface ObjectStorage {
    healthcheck: () => Promise<boolean>
    s3: S3Client
}

let objectStorage: ObjectStorage | undefined

export const getObjectStorage = (serverConfig: Partial<PluginsServerConfig>): ObjectStorage | undefined => {
    if (!objectStorage) {
        try {
            const {
                OBJECT_STORAGE_ENDPOINT,
                OBJECT_STORAGE_REGION,
                OBJECT_STORAGE_ACCESS_KEY_ID,
                OBJECT_STORAGE_SECRET_ACCESS_KEY,
                OBJECT_STORAGE_ENABLED,
                OBJECT_STORAGE_BUCKET,
            } = serverConfig

            if (OBJECT_STORAGE_ENABLED) {
                const credentials =
                    OBJECT_STORAGE_ACCESS_KEY_ID && OBJECT_STORAGE_SECRET_ACCESS_KEY
                        ? {
                              accessKeyId: OBJECT_STORAGE_ACCESS_KEY_ID,
                              secretAccessKey: OBJECT_STORAGE_SECRET_ACCESS_KEY,
                          }
                        : undefined

                const S3 = new S3Client({
                    region: OBJECT_STORAGE_REGION,
                    endpoint: OBJECT_STORAGE_ENDPOINT,
                    credentials,
                    forcePathStyle: true, // needed with minio?
                    // signatureVersion: 'v4',
                })

                objectStorage = {
                    healthcheck: async () => {
                        if (!OBJECT_STORAGE_BUCKET) {
                            logger.error('😢', 'No object storage bucket configured')
                            return false
                        }

                        try {
                            await S3.send(new HeadBucketCommand({ Bucket: OBJECT_STORAGE_BUCKET }))
                            return true
                        } catch (error) {
                            logger.error('💣', 'Could not access bucket:', error)
                            return false
                        }
                    },
                    s3: S3,
                }
            }
        } catch (e) {
            // only warn here... object storage is not mandatory until after #9901 at the earliest
            logger.warn('😢', 'could not initialise storage:', e)
        }
    }

    return objectStorage
}
