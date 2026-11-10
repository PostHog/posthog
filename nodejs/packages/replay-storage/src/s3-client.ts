import { S3Client, S3ClientConfig } from '@aws-sdk/client-s3'

/** The `SESSION_RECORDING_V2_S3_*` settings needed to build the recordings S3 client. */
export interface SessionRecordingS3Config {
    SESSION_RECORDING_V2_S3_ENDPOINT: string
    SESSION_RECORDING_V2_S3_REGION: string
    SESSION_RECORDING_V2_S3_BUCKET: string
    SESSION_RECORDING_V2_S3_PREFIX: string
    SESSION_RECORDING_V2_S3_ACCESS_KEY_ID: string
    SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY: string
}

/** Builds the recordings S3 client from config, or null when the settings are incomplete. */
export function buildSessionRecordingS3Client(config: SessionRecordingS3Config): S3Client | null {
    if (
        !config.SESSION_RECORDING_V2_S3_ENDPOINT ||
        !config.SESSION_RECORDING_V2_S3_REGION ||
        !config.SESSION_RECORDING_V2_S3_BUCKET ||
        !config.SESSION_RECORDING_V2_S3_PREFIX
    ) {
        return null
    }

    const s3Config: S3ClientConfig = {
        region: config.SESSION_RECORDING_V2_S3_REGION,
        endpoint: config.SESSION_RECORDING_V2_S3_ENDPOINT,
        forcePathStyle: true,
    }
    if (config.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID && config.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY) {
        s3Config.credentials = {
            accessKeyId: config.SESSION_RECORDING_V2_S3_ACCESS_KEY_ID,
            secretAccessKey: config.SESSION_RECORDING_V2_S3_SECRET_ACCESS_KEY,
        }
    }
    return new S3Client(s3Config)
}
