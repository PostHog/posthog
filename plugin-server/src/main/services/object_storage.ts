import { defaultConfig } from '../../config/config'

const aws = require('aws-sdk')

export const S3 = new aws.S3({
    endpoint: `http://${defaultConfig.MINIO_HOST}:${defaultConfig.MINIO_PORT}`,
    accessKeyId: defaultConfig.MINIO_ACCESS_KEY_ID,
    secretAccessKey: defaultConfig.MINIO_SECRET_ACCESS_KEY,
    s3ForcePathStyle: true, // needed with minio?
    signatureVersion: 'v4',
})
