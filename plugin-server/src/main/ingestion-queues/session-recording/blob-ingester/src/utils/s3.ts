import { S3Client } from '@aws-sdk/client-s3'
import { config } from '../config'

const credentials = config.s3.accessKeyId
    ? {
          accessKeyId: config.s3.accessKeyId,
          secretAccessKey: config.s3.secretAccessKey,
      }
    : undefined

// Create an Amazon S3 service client object.
export const s3Client = new S3Client({
    region: config.s3.region,
    endpoint: config.s3.endpoint,
    credentials: credentials,
    forcePathStyle: true, // Needed to work with MinIO
})
