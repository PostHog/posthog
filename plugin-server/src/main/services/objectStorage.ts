import { PluginsServerConfig } from '../../types'
import { status } from '../../utils/status'

const aws = require('aws-sdk')

let S3: typeof aws.S3 | null = null

export interface ObjectStorage {
    isEnabled: boolean
    putObject: (params: { Bucket: string; Body: any; Key: string }) => Promise<void>
    sessionRecordingAllowList: number[]
    healthcheck: () => Promise<boolean>
}

// Object Storage added without any uses to flush out deployment concerns.
// see https://github.com/PostHog/posthog/pull/9901
export const connectObjectStorage = (serverConfig: Partial<PluginsServerConfig>): ObjectStorage => {
    let storage: ObjectStorage = {
        isEnabled: false,
        putObject: () => Promise.resolve(),
        sessionRecordingAllowList: [],
        healthcheck: async () => {
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

            storage = {
                isEnabled: OBJECT_STORAGE_ENABLED,
                putObject: OBJECT_STORAGE_ENABLED
                    ? (params) => S3.putObject(params).promise()
                    : () => Promise.resolve(),
                sessionRecordingAllowList: Array.from(
                    new Set(
                        serverConfig.OBJECT_STORAGE_SESSION_RECORDING_ENABLED_TEAMS?.split(',')
                            .filter(String)
                            .map(Number)
                    )
                ),
                healthcheck: async () => {
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
                        status.error('💣', 'Could not access bucket:', error)
                        return false
                    }
                },
            }
        }
    } catch (e) {
        // only warn here... object storage is not mandatory until after #9901 at the earliest
        status.warn('😢', 'could not initialise storage:', e)
    }

    return storage
}
